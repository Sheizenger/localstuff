"""Бэкенд памяти поверх Hindsight.

Hindsight (vectorize-io/hindsight) хранит память банками и умеет то, чего
локальный SQLite не умеет: сводит разрозненные записи в наблюдения и
ментальные модели, то есть синтезирует понимание, а не только ищет по
похожести. Это и есть механизм постоянного улучшения — система не просто
накапливает факты, а перестраивает из них представление о проекте.

Два обстоятельства определяют, как он здесь встроен.

Первое: Hindsight — сервер и требует LLM-ключ (тип памяти определяется
извлечением через модель на каждом retain). Сделать его единственной
памятью значило бы сломать свойство, на котором держится вся система:
работать без единого ключа. Поэтому он опционален.

Второе: раз он опционален, он не может быть источником правды. Каждая
запись сначала ложится в локальный SQLite и только потом уходит в
Hindsight. Недоступность сервера, отозванный ключ или сетевой сбой не
теряют знание и не роняют миссию — поиск просто возвращается к локальному.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Any

from ..bus import EV_MEMORY_WRITE, EV_PROVIDER_ERROR
from .semantic import KIND_FACT, Fact, SemanticMemory

#: Префиксы тегов. Hindsight сам решает, что за тип памяти он хранит, а нам
#: нужно уметь отфильтровать своё: уроки отдельно от фактов, миссию отдельно.
TAG_KIND = "kind"
TAG_MISSION = "mission"

MODE_SERVER = "server"
MODE_EMBEDDED = "embedded"


class HindsightUnavailable(RuntimeError):
    """Бэкенд не поднялся. Наружу не выходит — приводит к работе на локальном."""


class HindsightMemory:
    """Локальная память плюс синтез Hindsight поверх неё.

    Реализует тот же протокол, что и SemanticMemory, поэтому оркестратор,
    критик и субагенты не знают, какой бэкенд под ними.
    """

    name = "hindsight"
    can_reflect = True

    def __init__(
        self,
        local: SemanticMemory,
        config: Any,
        *,
        bus: Any = None,
        ledger: Any = None,
        client: Any = None,
    ) -> None:
        self.local = local
        self.config = config
        self.bus = bus
        self.ledger = ledger
        self._client: Any = client
        self._server: Any = None
        self._failed_at: float = 0.0
        # Сколько молчать после сбоя, чтобы не долбить лежащий сервер на
        # каждом поиске: миссия из десятков задач иначе тратит минуты на таймауты.
        self._cooldown_s = float(self._cfg("cooldown_s", 60))

    # ------------------------------------------------------------- конфиг
    def _cfg(self, key: str, default: Any = None) -> Any:
        return self.config.get(f"memory.hindsight.{key}", default)

    @property
    def bank_id(self) -> str:
        """Банк памяти. По умолчанию — имя проекта: знание копится по проекту."""
        configured = str(self._cfg("bank_id", "") or "")
        return configured or f"agentos-{self.config.root.name}"

    @property
    def mode(self) -> str:
        return str(self._cfg("mode", MODE_SERVER))

    # ------------------------------------------------------------- клиент
    def _in_cooldown(self) -> bool:
        return bool(self._failed_at) and (time.time() - self._failed_at) < self._cooldown_s

    def _note_failure(self, operation: str, exc: Exception) -> None:
        self._failed_at = time.time()
        if self.bus is not None:
            self.bus.emit(
                EV_PROVIDER_ERROR,
                actor="hindsight",
                operation=operation,
                error=f"{type(exc).__name__}: {exc}"[:400],
                summary=f"Hindsight недоступен, работаем на локальной памяти ({operation})",
            )

    def client(self) -> Any:
        """Поднять клиент лениво. Бросает HindsightUnavailable, не наружу.

        Кулдаун проверяется до возврата уже построенного клиента: сервер мог
        лечь после того, как клиент создан, и без этой проверки каждая
        задача миссии платила бы полным таймаутом за один и тот же отказ.
        """
        if self._in_cooldown():
            raise HindsightUnavailable("недавний сбой, ждём остывания")
        if self._client is not None:
            return self._client

        if self.mode == MODE_EMBEDDED:
            self._client = self._start_embedded()
        else:
            self._client = self._connect_server()
        return self._client

    def _connect_server(self) -> Any:
        try:
            from hindsight_client import Hindsight
        except ImportError as exc:
            raise HindsightUnavailable(
                "не установлен клиент: uv pip install 'agentos[hindsight]'"
            ) from exc
        base_url = str(self._cfg("base_url", "") or os.environ.get("HINDSIGHT_BASE_URL", ""))
        if not base_url:
            raise HindsightUnavailable(
                "не задан memory.hindsight.base_url (или HINDSIGHT_BASE_URL)"
            )
        return Hindsight(
            base_url=base_url,
            api_key=os.environ.get("HINDSIGHT_API_KEY") or None,
            timeout=float(self._cfg("timeout_s", 60)),
        )

    def _start_embedded(self) -> Any:
        """Встроенный режим: поднимаем сервер в этом же процессе.

        Он всё равно остаётся процессом с базой и требует ключ модели —
        поэтому режим по умолчанию не встроенный, а внешний сервер.
        """
        try:
            from hindsight import HindsightClient, HindsightServer
        except ImportError as exc:
            raise HindsightUnavailable(
                "встроенный режим требует пакет hindsight-all"
            ) from exc
        provider = str(self._cfg("llm_provider", "openai"))
        key_env = str(self._cfg("llm_api_key_env", "OPENAI_API_KEY"))
        api_key = os.environ.get(key_env)
        if not api_key:
            raise HindsightUnavailable(f"нет ключа модели в {key_env}")
        self._server = HindsightServer(
            llm_provider=provider,
            llm_model=str(self._cfg("llm_model", "gpt-5-mini")),
            llm_api_key=api_key,
        )
        self._server.__enter__()
        return HindsightClient(base_url=self._server.url)

    def available(self) -> bool:
        """Локальная половина доступна всегда, поэтому бэкенд — тоже."""
        return self.local.available()

    def remote_available(self) -> bool:
        """Отвечает ли сейчас сам Hindsight — не «построился ли клиент».

        Построенный клиент ничего не доказывает: он не ходит в сеть до
        первого вызова. Поэтому спрашиваем версию.
        """
        try:
            client = self.client()
            probe = getattr(client, "get_version", None)
            if callable(probe):
                probe()
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Закрыть клиент и, во встроенном режиме, сервер.

        Клиент держит HTTP-сессию: без явного закрытия она остаётся висеть,
        и рантайм при выходе жалуется на брошенное соединение.
        """
        if self._client is not None:
            closer = getattr(self._client, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    pass
        if self._server is not None:
            try:
                self._server.__exit__(None, None, None)
            except Exception:
                pass
            self._server = None
        self._client = None

    # ------------------------------------------------------------- запись
    def add(
        self,
        content: str,
        *,
        kind: str = KIND_FACT,
        subject: str = "",
        source: str = "",
        confidence: float = 0.5,
        mission_id: str = "",
        dedupe: bool = True,
    ) -> str:
        """Записать знание: сначала локально, затем в Hindsight.

        Порядок не переставить: локальная запись durable и бесплатна, а
        retain делает извлечение через модель и может не дойти.
        """
        fact_id = self.local.add(
            content,
            kind=kind,
            subject=subject,
            source=source,
            confidence=confidence,
            mission_id=mission_id,
            dedupe=dedupe,
        )
        if not fact_id or not self._cfg("mirror", True):
            return fact_id

        try:
            client = self.client()
            response = client.retain(
                bank_id=self.bank_id,
                content=content,
                context=subject or None,
                timestamp=datetime.now(UTC),
                document_id=fact_id,
                metadata={
                    "source": source or "agentos",
                    "confidence": f"{confidence:.2f}",
                    "local_id": fact_id,
                },
                tags=self._tags(kind, mission_id),
                retain_async=bool(self._cfg("retain_async", True)),
            )
            self._record_usage(getattr(response, "usage", None), "retain", mission_id)
        except Exception as exc:
            # Знание уже сохранено локально — сбой синхронизации не потеря.
            self._note_failure("retain", exc)
        return fact_id

    @staticmethod
    def _tags(kind: str, mission_id: str) -> list[str]:
        tags = [f"{TAG_KIND}:{kind}"]
        if mission_id:
            tags.append(f"{TAG_MISSION}:{mission_id}")
        return tags

    def add_many(self, items: list[dict[str, Any]], *, mission_id: str = "") -> list[str]:
        return [
            self.add(
                item.get("content", ""),
                kind=item.get("kind", KIND_FACT),
                subject=item.get("subject", ""),
                source=item.get("source", ""),
                confidence=float(item.get("confidence", 0.5)),
                mission_id=mission_id,
            )
            for item in items
            if item.get("content")
        ]

    # ------------------------------------------------------------- чтение
    def search(
        self,
        query: str,
        *,
        limit: int = 12,
        kinds: tuple[str, ...] = (),
        rrf_k: int = 60,
    ) -> list[Fact]:
        """Искать в Hindsight, при любой заминке — в локальной памяти.

        Результаты двух бэкендов намеренно не смешиваются: у них разные
        шкалы релевантности, и склейка без общей шкалы вернула бы ту же
        задачу калибровки, ради ухода от которой в локальном поиске выбран
        RRF. Hindsight отвечает — берём его ответ целиком; не отвечает или
        отвечает пусто — работает локальный.
        """
        if not query.strip():
            return []
        try:
            client = self.client()
            response = client.recall(
                bank_id=self.bank_id,
                query=query,
                max_tokens=int(self._cfg("recall_max_tokens", 4096)),
                budget=str(self._cfg("recall_budget", "mid")),
                tags=[f"{TAG_KIND}:{k}" for k in kinds] or None,
                tags_match="any",
                prefer_observations=bool(self._cfg("prefer_observations", True)),
            )
        except Exception as exc:
            self._note_failure("recall", exc)
            return self.local.search(query, limit=limit, kinds=kinds, rrf_k=rrf_k)

        facts = self._to_facts(getattr(response, "results", None) or [], limit)
        if not facts:
            return self.local.search(query, limit=limit, kinds=kinds, rrf_k=rrf_k)
        return facts

    def _to_facts(self, results: list[Any], limit: int) -> list[Fact]:
        """Привести ответ Hindsight к нашему Fact."""
        facts: list[Fact] = []
        for result in results[:limit]:
            tags = list(getattr(result, "tags", None) or [])
            kind = next(
                (t.split(":", 1)[1] for t in tags if t.startswith(f"{TAG_KIND}:")), KIND_FACT
            )
            mission = next(
                (t.split(":", 1)[1] for t in tags if t.startswith(f"{TAG_MISSION}:")), ""
            )
            metadata = dict(getattr(result, "metadata", None) or {})
            scores = getattr(result, "scores", None)
            score = float(getattr(scores, "final", 0.0) or 0.0) if scores else 0.0
            # Тип памяти самого Hindsight (наблюдение, ментальная модель)
            # ценнее нашего исходного вида записи — он и есть синтез.
            memory_type = str(getattr(result, "type", "") or "")
            facts.append(
                Fact(
                    id=str(getattr(result, "id", "")),
                    kind=kind,
                    subject=str(getattr(result, "context", "") or ""),
                    content=str(getattr(result, "text", "") or ""),
                    source=metadata.get("source", "")
                    or (f"hindsight/{memory_type}" if memory_type else "hindsight"),
                    confidence=float(metadata.get("confidence", 0.5) or 0.5),
                    mission_id=mission,
                    uses=0,
                    score=score,
                )
            )
        return [f for f in facts if f.content]

    def reflect(self, query: str, *, mission_id: str = "", context: str = "") -> str:
        """Синтез поверх накопленного: наблюдения и ментальные модели.

        Это то, ради чего внешний бэкенд вообще нужен. Локальный поиск
        возвращает похожие записи; reflect возвращает вывод из них.
        """
        try:
            client = self.client()
            response = client.reflect(
                bank_id=self.bank_id,
                query=query,
                budget=str(self._cfg("reflect_budget", "low")),
                context=context or None,
                max_tokens=int(self._cfg("reflect_max_tokens", 1500)),
            )
        except Exception as exc:
            self._note_failure("reflect", exc)
            return ""
        self._record_usage(getattr(response, "usage", None), "reflect", mission_id)
        text = str(getattr(response, "text", "") or "").strip()
        if text and self.bus is not None:
            self.bus.emit(
                EV_MEMORY_WRITE,
                mission_id=mission_id,
                actor="hindsight",
                operation="reflect",
                summary=text[:300],
            )
        return text

    # ------------------------------------------------------------- прочее
    def _record_usage(self, usage: Any, operation: str, mission_id: str) -> None:
        """Завести расход Hindsight в общий леджер.

        Его извлечение и синтез стоят токенов у стороннего провайдера. Не
        учитывать их значило бы показывать человеку заниженный расход.
        """
        if usage is None or self.ledger is None:
            return
        tokens_in = int(getattr(usage, "input_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "output_tokens", 0) or 0)
        if not (tokens_in or tokens_out):
            return
        self.ledger.record(
            provider="hindsight",
            model=str(self._cfg("llm_model", "gpt-5-mini")),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cached_in=int(getattr(usage, "cached_tokens", 0) or 0),
            mission_id=mission_id,
            kind=f"memory.{operation}",
        )

    # Операции, которых у Hindsight нет, обслуживает локальная половина.
    def touch(self, fact_id: str) -> None:
        self.local.touch(fact_id)

    def forget(self, fact_id: str) -> None:
        self.local.forget(fact_id)

    def get(self, fact_id: str) -> Fact | None:
        return self.local.get(fact_id)

    def recent(self, *, kind: str = "", limit: int = 20) -> list[Fact]:
        return self.local.recent(kind=kind, limit=limit)

    def reindex_vectors(self) -> int:
        return self.local.reindex_vectors()

    @property
    def index(self) -> Any:
        return self.local.index

    @property
    def embedder(self) -> Any:
        return self.local.embedder

    def stats(self) -> dict[str, int]:
        return self.local.stats()
