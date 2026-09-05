"""Память: поиск, дедупликация, экономия контекста."""

from __future__ import annotations

import pytest

from agentos.memory.semantic import KIND_LESSON, SemanticMemory
from agentos.memory.vector import Embedder, cosine, hash_embed, pack, unpack
from agentos.memory.working import Brief, WorkingMemory, estimate_tokens


@pytest.fixture
def memory(store, config):
    return SemanticMemory(store, Embedder(config), config)


def test_local_embedding_is_deterministic_and_normalized():
    first = hash_embed("автономный агент с памятью")
    second = hash_embed("автономный агент с памятью")
    assert first == second
    assert cosine(first, second) == pytest.approx(1.0)
    assert cosine(first, hash_embed("рецепт борща")) < 0.5


def test_vector_survives_storage_roundtrip():
    vector = hash_embed("проверка сериализации")
    assert unpack(pack(vector)) == pytest.approx(vector, abs=1e-6)


def test_duplicate_facts_are_merged(memory):
    first = memory.add("Тесты запускаются через make test", subject="сборка")
    second = memory.add("Тесты запускаются через make test", subject="сборка")
    assert first == second
    assert memory.stats()["fact"] == 1


def test_keyword_search_finds_exact_wording(memory):
    memory.add("Линтер — ruff, конфиг в pyproject.toml", subject="сборка")
    memory.add("Планировщик держит резерв бюджета", kind=KIND_LESSON, subject="бюджет")

    found = memory.search("ruff")
    assert found
    assert "ruff" in found[0].content


def test_search_survives_fts_metacharacters(memory):
    """Пользовательский текст в MATCH рушит FTS5 — запрос должен экранироваться."""
    memory.add("что-то полезное про сборку", subject="сборка")
    assert memory.search('"незакрытая кавычка AND (') is not None


def test_brief_shrinks_without_losing_the_goal(config):
    working = WorkingMemory(config)
    brief = Brief(
        mission_goal="важная цель",
        task_title="задача",
        instructions="что сделать",
        acceptance=["критерий приёмки"],
        memory=[f"- факт {i}" for i in range(50)],
        skills=[f"- навык {i}" for i in range(20)],
        inputs=["А" * 8000],
    )
    assert brief.tokens() > 1000

    working.fit_brief(brief, 400)

    rendered = brief.render()
    assert "важная цель" in rendered, "цель нельзя срезать ни при каком бюджете"
    assert "критерий приёмки" in rendered
    assert brief.skills == [] and brief.memory == [], "первыми режутся навыки и память"
    assert estimate_tokens(rendered) < 700


def test_skill_catalog_exposes_headers_only(runtime):
    """Постепенное раскрытие: тело навыка не попадает в контекст само."""
    runtime.sync_skills()
    catalog = runtime.skills.catalog()
    assert catalog, "стартовые навыки должны индексироваться"
    for skill in catalog:
        assert skill.body == ""
        assert skill.description

    loaded = runtime.skills.load(catalog[0].name)
    assert len(loaded.body) > 100


def test_vector_backend_is_a_real_switch(store):
    """Конфиг обещал sqlite-vec, которого не было; теперь значения честные."""
    from agentos.memory.vector import BACKENDS, BruteForceIndex

    assert set(BACKENDS) == {"auto", "numpy", "python", "off"}

    auto = BruteForceIndex(store, "auto")
    assert auto.enabled
    assert auto.backend in ("numpy", "python")

    off = BruteForceIndex(store, "off")
    assert not off.enabled
    assert off.backend == "off"
    assert off.search([0.1] * 512) == [], "выключенный бэкенд не должен искать"

    with pytest.raises(ValueError, match="sqlite-vec"):
        BruteForceIndex(store, "sqlite-vec")


def test_search_still_works_with_vectors_off(store, config, monkeypatch):
    """BM25 обязан продолжать работать: поиск не должен исчезать целиком."""
    from agentos.memory.semantic import SemanticMemory
    from agentos.memory.vector import Embedder

    monkeypatch.setitem(config.main["memory"]["vector"], "backend", "off")
    memory = SemanticMemory(store, Embedder(config), config)
    memory.add("Линтер — ruff, конфиг в pyproject.toml", subject="сборка")

    assert not memory.index.enabled
    found = memory.search("ruff")
    assert found and "ruff" in found[0].content
