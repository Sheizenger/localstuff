"""Контракт бэкенда семантической памяти.

Зачем слой: у AgentOS два несовместимых требования к памяти. Она обязана
работать без единого API-ключа (на этом держатся тесты и native-режим) — и
при этом хотелось бы синтеза поверх накопленного, который без модели
получить нельзя.

Решение — не выбирать, а разделить роли:

  SQLite-бэкенд      всегда доступен, durable, источник правды;
  Hindsight-бэкенд   опционален, добавляет консолидацию наблюдений и
                     ментальные модели поверх тех же записей.

Оба реализуют этот протокол, поэтому оркестратор, критик и субагенты не
знают, какой из них под ними, — ровно как с провайдерами моделей.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .semantic import Fact


@runtime_checkable
class MemoryBackend(Protocol):
    """Минимум, который нужен системе от долговременной памяти."""

    #: Имя для diagnostics и логов: sqlite, hindsight, …
    name: str

    def available(self) -> bool:
        """Готов ли бэкенд принимать запросы прямо сейчас."""

    def add(
        self,
        content: str,
        *,
        kind: str = "fact",
        subject: str = "",
        source: str = "",
        confidence: float = 0.5,
        mission_id: str = "",
        dedupe: bool = True,
    ) -> str:
        """Записать факт, урок или решение. Возвращает id записи."""

    def search(
        self,
        query: str,
        *,
        limit: int = 12,
        kinds: tuple[str, ...] = (),
        rrf_k: int = 60,
    ) -> list[Fact]:
        """Найти релевантное. Пустой список — валидный ответ."""

    def stats(self) -> dict[str, int]:
        """Сколько чего накоплено."""

    def get(self, fact_id: str) -> Fact | None:
        """Достать запись по id."""

    def touch(self, fact_id: str) -> None:
        """Отметить обращение к записи — по этому видно, что реально нужно."""

    def forget(self, fact_id: str) -> None:
        """Забыть запись."""

    def recent(self, *, kind: str = "", limit: int = 20) -> list[Fact]:
        """Последние записи заданного вида."""

    def reindex_vectors(self) -> int:
        """Пересчитать эмбеддинги при смене модели. Возвращает число записей."""

    @property
    def index(self) -> Any:
        """Векторный индекс — нужен диагностике."""

    @property
    def embedder(self) -> Any:
        """Модель эмбеддингов — нужна диагностике."""


def supports_reflection(backend: Any) -> bool:
    """Умеет ли бэкенд синтезировать знание, а не только искать.

    Проверяется явно, а не через hasattr на каждом вызове: наличие метода
    ещё не значит, что бэкенд сейчас доступен.
    """
    return bool(getattr(backend, "can_reflect", False)) and backend.available()
