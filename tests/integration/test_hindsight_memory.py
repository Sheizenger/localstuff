"""Бэкенд памяти Hindsight — без сети и без сервера.

Проверяется то, ради чего этот слой устроен именно так: знание не теряется,
когда внешняя память недоступна, и миссия из-за неё не встаёт.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from agentos.memory.backend import supports_reflection
from agentos.memory.hindsight import TAG_KIND, TAG_MISSION, HindsightMemory
from agentos.memory.semantic import KIND_LESSON


class FakeHindsight:
    """Заглушка клиента: записывает вызовы и отдаёт заданные ответы."""

    def __init__(self, *, results=None, reflection="", fail=None):
        self.retained: list[dict] = []
        self.recalls: list[dict] = []
        self.reflects: list[dict] = []
        # Попытки считаются отдельно от успехов: проверка кулдауна должна
        # видеть именно обращения в сеть, а не только удавшиеся.
        self.attempts: list[str] = []
        self._results = results or []
        self._reflection = reflection
        self._fail = fail or set()

    def _maybe_fail(self, op):
        if op in self._fail:
            raise RuntimeError(f"Hindsight недоступен: {op}")

    def retain(self, **kwargs):
        self.attempts.append("retain")
        self._maybe_fail("retain")
        self.retained.append(kwargs)
        return SimpleNamespace(
            success=True,
            items_count=1,
            usage=SimpleNamespace(input_tokens=120, output_tokens=30, cached_tokens=0),
        )

    def recall(self, **kwargs):
        self.attempts.append("recall")
        self._maybe_fail("recall")
        self.recalls.append(kwargs)
        return SimpleNamespace(results=self._results)

    def reflect(self, **kwargs):
        self.attempts.append("reflect")
        self._maybe_fail("reflect")
        self.reflects.append(kwargs)
        return SimpleNamespace(
            text=self._reflection,
            usage=SimpleNamespace(input_tokens=800, output_tokens=200, cached_tokens=64),
        )

    def get_version(self):
        self.attempts.append("version")
        self._maybe_fail("version")
        return SimpleNamespace(version="test")


def result(text, *, id="h1", tags=(), context="", score=0.9, type="observation"):
    return SimpleNamespace(
        id=id,
        text=text,
        type=type,
        context=context,
        tags=list(tags),
        metadata={"source": "тест"},
        scores=SimpleNamespace(final=score),
    )


@pytest.fixture
def backend(runtime):
    def build(client):
        return HindsightMemory(
            runtime.local_memory, runtime.config, bus=runtime.bus,
            ledger=runtime.ledger, client=client,
        )

    return build


def test_write_lands_locally_and_is_mirrored(backend, runtime):
    client = FakeHindsight()
    memory = backend(client)

    fact_id = memory.add(
        "Тесты запускаются через make test",
        kind="fact", subject="сборка", source="Makefile", mission_id="m1",
    )

    assert fact_id, "локальная запись — источник правды, id обязателен"
    assert runtime.local_memory.get(fact_id) is not None

    assert len(client.retained) == 1
    sent = client.retained[0]
    assert sent["content"].startswith("Тесты запускаются")
    assert sent["context"] == "сборка"
    assert f"{TAG_KIND}:fact" in sent["tags"]
    assert f"{TAG_MISSION}:m1" in sent["tags"]
    assert sent["metadata"]["local_id"] == fact_id


def test_knowledge_is_not_lost_when_the_server_is_down(backend, runtime):
    """Сбой синхронизации не должен стоить записи."""
    memory = backend(FakeHindsight(fail={"retain"}))

    fact_id = memory.add("Линтер — ruff", subject="сборка")

    assert fact_id
    assert runtime.local_memory.get(fact_id).content == "Линтер — ruff"


def test_search_returns_hindsight_results(backend):
    client = FakeHindsight(
        results=[
            result("Проект собирается через uv", tags=[f"{TAG_KIND}:fact"], context="сборка"),
            result("Планировщик держит резерв", id="h2", tags=[f"{TAG_KIND}:lesson"]),
        ]
    )
    memory = backend(client)

    found = memory.search("как собирается проект", limit=5)

    assert [f.content for f in found] == [
        "Проект собирается через uv",
        "Планировщик держит резерв",
    ]
    assert found[0].kind == "fact"
    assert found[1].kind == "lesson"
    assert found[0].score == pytest.approx(0.9)
    assert client.recalls[0]["bank_id"] == memory.bank_id


def test_search_falls_back_to_local_when_recall_fails(backend, runtime):
    runtime.local_memory.add("Локальный факт про сборку", subject="сборка")
    memory = backend(FakeHindsight(fail={"recall"}))

    found = memory.search("сборка")

    assert found, "поиск обязан продолжать работать на локальной памяти"
    assert "Локальный факт" in found[0].content


def test_search_falls_back_when_hindsight_is_empty(backend, runtime):
    runtime.local_memory.add("Локальный факт про линтер", subject="сборка")
    memory = backend(FakeHindsight(results=[]))

    found = memory.search("линтер")

    assert found and "линтер" in found[0].content


def test_failure_puts_the_backend_on_cooldown(backend):
    """Иначе каждая задача миссии платит полным таймаутом за один отказ."""
    client = FakeHindsight(fail={"recall"})
    memory = backend(client)
    memory._cooldown_s = 60

    memory.search("первый запрос")
    attempts_after_first = len(client.attempts)
    assert attempts_after_first == 1

    memory.search("второй запрос")
    assert len(client.attempts) == attempts_after_first, "во время остывания в сеть не ходим"

    memory._failed_at = time.time() - 120
    memory.search("после остывания")
    assert len(client.attempts) > attempts_after_first, "после остывания пробуем снова"


def test_reflect_returns_synthesis_and_is_billed(backend, runtime):
    client = FakeHindsight(reflection="Проект собирается uv, тесты гоняются make test.")
    memory = backend(client)
    mission_id = runtime.sm.create_mission("миссия для учёта расхода", budget_tokens=100_000)

    text = memory.reflect("что известно о проекте", mission_id=mission_id)

    assert text.startswith("Проект собирается")
    assert supports_reflection(memory)
    spend = runtime.ledger.mission_spend(mission_id)
    assert spend.tokens == 1000, "расход внешней памяти должен попадать в общий леджер"


def test_reflect_is_silent_when_unavailable(backend):
    memory = backend(FakeHindsight(fail={"reflect"}))
    assert memory.reflect("что известно") == ""


def test_mission_synthesis_is_stored_locally_only(backend, runtime, monkeypatch):
    """Синтез не уходит обратно во внешнюю память: иначе она обобщает своё эхо."""
    from agentos.orchestrator.improve import Improver

    client = FakeHindsight(reflection="Вывод: сборка на uv, гейты зелёные.")
    memory = backend(client)
    monkeypatch.setitem(runtime.__dict__, "semantic", memory)

    mission_id = runtime.sm.create_mission("собрать обзор проекта")
    text = Improver(runtime).reflect_on_mission(mission_id)

    assert text.startswith("Вывод:")
    lessons = runtime.local_memory.recent(kind=KIND_LESSON)
    assert any("Вывод:" in lesson.content for lesson in lessons)
    assert client.retained == [], "синтез не должен возвращаться в Hindsight"


def test_local_backend_reports_no_reflection(runtime):
    assert runtime.semantic.name == "sqlite"
    assert not supports_reflection(runtime.semantic)


def test_close_releases_the_client_session(backend):
    """Клиент держит HTTP-сессию: брошенная утекает и шумит в выводе."""
    class ClosableFake(FakeHindsight):
        def __init__(self):
            super().__init__()
            self.closed = False

        def close(self):
            self.closed = True

    client = ClosableFake()
    memory = backend(client)
    memory.add("что-нибудь", subject="тест")

    memory.close()

    assert client.closed
