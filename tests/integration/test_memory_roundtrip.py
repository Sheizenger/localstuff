"""Память в связке: запись прогона → консолидация → поиск → бриф субагента.

По отдельности слои проверены юнит-тестами; здесь важно, что знание,
добытое одной миссией, реально доезжает до следующей задачи.
"""

from __future__ import annotations

from agentos.memory.semantic import KIND_LESSON
from agentos.orchestrator.improve import Improver
from agentos.orchestrator.supervisor import Supervisor


def test_knowledge_from_a_run_reaches_the_next_brief(runtime):
    # Прогон, после которого что-то должно остаться в памяти.
    supervisor = Supervisor(runtime)
    mission_id, _spec, _result = supervisor.start("собрать сводку по проекту")
    Improver(runtime).consolidate(mission_id)

    # Явное знание проекта, которое обязано находиться по смыслу задачи.
    runtime.semantic.add(
        "Тесты проекта запускаются командой make test",
        subject="сборка",
        source="Makefile",
    )

    brief = runtime.working.build_brief(
        mission_goal="починить сборку",
        task_title="разобраться, как запускаются тесты",
        instructions="найди команду запуска тестов",
    )

    assert any("make test" in line for line in brief.memory), (
        "факт из памяти должен попадать в бриф следующей задачи"
    )
    assert brief.skills, "к задаче должны подтягиваться подходящие навыки"


def test_retro_records_repeated_attempts_as_lessons(runtime):
    """Повторные попытки — сигнал, что что-то устроено неудобно."""
    mission_id = runtime.sm.create_mission("миссия с повторами")
    task_id = runtime.sm.add_task(mission_id, title="капризная задача", role="coder")
    runtime.store.execute(
        "UPDATE tasks SET attempts=3, blocked_reason='гейт красный' WHERE id=?", (task_id,)
    )

    written = Improver(runtime).retro(mission_id)

    assert written
    lessons = runtime.semantic.recent(kind=KIND_LESSON)
    assert any("капризная задача" in lesson.content for lesson in lessons)


def test_proposed_skill_is_not_active_until_promoted(runtime):
    """Самопишущийся навык не должен молча попадать в контекст всех задач."""
    improver = Improver(runtime)
    path = improver.propose_skill(
        name="test-navyk",
        description="черновик из теста",
        triggers=["черновик"],
        body="Шаги: раз, два, три.",
    )
    assert path is not None
    runtime.sync_skills()

    active_names = {s.name for s in runtime.skills.catalog()}
    assert "test-navyk" not in active_names
    assert "test-navyk" in improver.proposed()

    assert improver.promote_skill("test-navyk")
    assert "test-navyk" in {s.name for s in runtime.skills.catalog()}
    assert "test-navyk" not in improver.proposed()


def test_artifacts_are_addressed_by_hash(runtime):
    first = runtime.artifacts.put_text("report.md", "# отчёт", mission_id="m1")
    second = runtime.artifacts.put_text("report.md", "# отчёт", mission_id="m1")

    assert first.id == second.id, "одинаковый результат не должен раздваиваться"
    assert runtime.artifacts.read(first.id) == "# отчёт"
