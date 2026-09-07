"""Память двух уровней: что остаётся в проекте, а что переезжает с человеком."""

from __future__ import annotations

import pytest

from agentos.memory.scoped import DEFAULT_GLOBAL_KINDS, ScopedMemory
from agentos.memory.semantic import KIND_DECISION, KIND_FACT, KIND_LESSON, KIND_PREFERENCE


@pytest.fixture
def memory(runtime):
    return runtime.semantic


def test_facts_stay_in_the_project(memory, runtime):
    fact_id = memory.add("Тесты здесь запускаются через make test", kind=KIND_FACT)

    assert runtime.local_memory.get(fact_id) is not None
    assert runtime.shared_memory.get(fact_id) is None


def test_lessons_travel_with_the_person(memory, runtime):
    lesson_id = memory.add("Красный гейт нельзя переспорить", kind=KIND_LESSON)

    assert runtime.shared_memory.get(lesson_id) is not None
    assert runtime.local_memory.get(lesson_id) is None


@pytest.mark.parametrize(
    ("kind", "shared"),
    [
        (KIND_FACT, False),
        (KIND_DECISION, False),
        (KIND_LESSON, True),
        (KIND_PREFERENCE, True),
    ],
)
def test_routing_by_kind(memory, kind, shared):
    target = memory.target_for(kind)
    assert (target is memory.shared) is shared


def test_search_covers_both_levels(memory):
    memory.add("Линтер проекта — ruff", kind=KIND_FACT, subject="сборка")
    memory.add("Не глушить линтер ради зелёного гейта", kind=KIND_LESSON, subject="приёмка")

    found = {fact.content for fact in memory.search("линтер")}

    assert any("ruff" in c for c in found)
    assert any("глушить" in c for c in found)


def test_project_knowledge_outranks_general_rule(memory):
    """Знание о конкретном репозитории точнее общего правила."""
    memory.add("Сборка проекта идёт через uv", kind=KIND_FACT, subject="сборка")
    memory.add("Сборка обычно идёт через пакетный менеджер", kind=KIND_LESSON, subject="сборка")

    found = memory.search("как идёт сборка")

    assert found
    assert "uv" in found[0].content


def test_sharing_can_be_switched_off(runtime, monkeypatch):
    """Проект может захотеть полной изоляции."""
    monkeypatch.setitem(runtime.config.main["memory"], "share_across_projects", False)
    runtime.__dict__.pop("semantic", None)  # сбросить закешированное свойство

    assert runtime.semantic.name == "sqlite"


def test_default_global_kinds_are_narrow():
    """Общей становится только та память, что действительно применима везде."""
    assert set(DEFAULT_GLOBAL_KINDS) == {KIND_LESSON, KIND_PREFERENCE}


def test_stats_separate_the_levels(memory):
    memory.add("проектный факт", kind=KIND_FACT)
    memory.add("общий урок", kind=KIND_LESSON)

    stats = memory.stats()

    assert stats.get("fact") == 1
    assert stats.get("общее:lesson") == 1


def test_scoped_memory_satisfies_the_backend_protocol(memory):
    from agentos.memory.backend import MemoryBackend

    assert isinstance(memory, MemoryBackend)
    assert isinstance(memory, ScopedMemory)
