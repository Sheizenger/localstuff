"""Память двух уровней: проектная и общая.

Когда AgentOS подключён к десятку проектов, у знания появляются два разных
срока годности. «Тесты здесь запускаются через make test» верно ровно для
одного репозитория и обязано остаться в нём. «Красный гейт нельзя
переспорить вердиктом модели» верно везде и должно переехать с человеком в
следующий проект.

Отсюда разделение:

  проектная память  <проект>/.agentos/var/agentos.db   факты и решения
  общая память      ~/.agentos/var/global.db           уроки и предпочтения

Читаются обе, пишется одна — по виду записи. Так агент приходит в новый
проект не с нуля, но и не тащит туда чужой контекст.
"""

from __future__ import annotations

from typing import Any

from .backend import MemoryBackend
from .semantic import KIND_FACT, KIND_LESSON, KIND_PREFERENCE, Fact

#: Виды записей, которые по умолчанию переезжают между проектами.
DEFAULT_GLOBAL_KINDS = (KIND_LESSON, KIND_PREFERENCE)


class ScopedMemory:
    """Обёртка над двумя бэкендами: проектным и общим."""

    name = "scoped"

    def __init__(
        self,
        project: MemoryBackend,
        shared: MemoryBackend,
        config: Any,
    ) -> None:
        self.project = project
        self.shared = shared
        self.config = config

    # ------------------------------------------------------------- свойства
    @property
    def can_reflect(self) -> bool:
        """Синтез умеет тот уровень, у которого настроен способный бэкенд."""
        return bool(getattr(self.project, "can_reflect", False))

    @property
    def global_kinds(self) -> tuple[str, ...]:
        configured = self.config.get("memory.global_kinds", None)
        if configured is None:
            return DEFAULT_GLOBAL_KINDS
        return tuple(str(k) for k in configured)

    def available(self) -> bool:
        return self.project.available()

    def target_for(self, kind: str) -> MemoryBackend:
        """Куда писать запись данного вида."""
        return self.shared if kind in self.global_kinds else self.project

    # --------------------------------------------------------------- запись
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
        return self.target_for(kind).add(
            content,
            kind=kind,
            subject=subject,
            source=source,
            confidence=confidence,
            mission_id=mission_id,
            dedupe=dedupe,
        )

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

    # --------------------------------------------------------------- чтение
    def search(
        self,
        query: str,
        *,
        limit: int = 12,
        kinds: tuple[str, ...] = (),
        rrf_k: int = 60,
    ) -> list[Fact]:
        """Искать на обоих уровнях и слить по рангам.

        Слияние по рангам, а не по абсолютным оценкам: у проектной и общей
        памяти разные корпуса, и одна и та же оценка значит в них разное.
        При равенстве рангов побеждает проектная — знание о конкретном
        репозитории точнее общего правила.
        """
        project_hits = self.project.search(query, limit=limit, kinds=kinds, rrf_k=rrf_k)
        shared_hits = self.shared.search(query, limit=limit, kinds=kinds, rrf_k=rrf_k)
        if not shared_hits:
            return project_hits
        if not project_hits:
            return shared_hits

        scores: dict[str, float] = {}
        facts: dict[str, Fact] = {}
        for weight, hits in ((1.0, project_hits), (0.999, shared_hits)):
            for rank, fact in enumerate(hits):
                key = fact.content.strip()
                scores[key] = scores.get(key, 0.0) + weight / (rrf_k + rank + 1)
                facts.setdefault(key, fact)

        ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        merged: list[Fact] = []
        for key, score in ordered:
            fact = facts[key]
            fact.score = score
            merged.append(fact)
        return merged

    def recent(self, *, kind: str = "", limit: int = 20) -> list[Fact]:
        target = self.target_for(kind) if kind else self.project
        return target.recent(kind=kind, limit=limit)

    def get(self, fact_id: str) -> Fact | None:
        return self.project.get(fact_id) or self.shared.get(fact_id)

    def touch(self, fact_id: str) -> None:
        if self.project.get(fact_id) is not None:
            self.project.touch(fact_id)
        else:
            self.shared.touch(fact_id)

    def forget(self, fact_id: str) -> None:
        self.project.forget(fact_id)
        self.shared.forget(fact_id)

    def reflect(self, query: str, *, mission_id: str = "", context: str = "") -> str:
        reflector = getattr(self.project, "reflect", None)
        if not callable(reflector):
            return ""
        return reflector(query, mission_id=mission_id, context=context)

    # --------------------------------------------------------------- прочее
    def stats(self) -> dict[str, int]:
        combined = dict(self.project.stats())
        for kind, count in self.shared.stats().items():
            combined[f"общее:{kind}"] = count
        return combined

    def reindex_vectors(self) -> int:
        return self.project.reindex_vectors() + self.shared.reindex_vectors()

    @property
    def index(self) -> Any:
        return self.project.index

    @property
    def embedder(self) -> Any:
        return self.project.embedder

    def close(self) -> None:
        for backend in (self.project, self.shared):
            closer = getattr(backend, "close", None)
            if callable(closer):
                closer()
