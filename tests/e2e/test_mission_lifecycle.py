"""Полный жизненный цикл миссии на mock-провайдере, без ключей и сети."""

from __future__ import annotations

from agentos.orchestrator.supervisor import Supervisor
from agentos.state.machine import TaskStatus


def test_abstract_goal_produces_a_plan_and_executed_tasks(runtime):
    supervisor = Supervisor(runtime)
    mission_id, spec, result = supervisor.start("составить обзор архитектуры проекта")

    assert spec.acceptance, "критерии приёмки фиксируются до начала работы"

    tasks = runtime.sm.tasks_of(mission_id)
    assert len(tasks) >= 3, "абстрактная цель должна раскладываться на задачи"
    assert any(t.status is TaskStatus.DONE for t in tasks)
    assert result.tick.executed > 0

    roles = {t.role for t in tasks}
    assert len(roles) > 1, "разные задачи должны получать разные роли"


def test_dod_is_recorded_before_work_starts(runtime):
    supervisor = Supervisor(runtime)
    mission_id, _spec, _result = supervisor.start("собрать сводку")

    criteria = runtime.store.query(
        "SELECT criterion, kind FROM dod WHERE mission_id=? ORDER BY ord", (mission_id,)
    )
    assert criteria
    assert any(c["kind"] == "programmatic" for c in criteria), (
        "программные гейты добавляются из конфига всегда"
    )


def test_dependent_task_receives_predecessor_result(runtime):
    """Иначе DAG разваливается на несвязанные шаги."""
    supervisor = Supervisor(runtime)
    mission_id, _spec, _result = supervisor.start("собрать и оформить отчёт")

    dependents = runtime.store.query(
        "SELECT DISTINCT task_id FROM task_deps WHERE task_id IN"
        " (SELECT id FROM tasks WHERE mission_id=?)",
        (mission_id,),
    )
    assert dependents, "план должен содержать зависимости"

    from agentos.orchestrator.dispatch import Dispatcher

    inputs = Dispatcher(runtime)._dependency_results(dependents[0]["task_id"])
    assert inputs, "результат предшественника должен попадать во входные данные"
    assert "из задачи" in inputs[0]


def test_spend_is_recorded_and_bounded(runtime):
    supervisor = Supervisor(runtime)
    mission_id, _spec, _result = supervisor.start("короткая задача")

    spend = runtime.ledger.mission_spend(mission_id)
    assert spend.tokens > 0, "расход должен учитываться"
    assert spend.tokens < spend.budget_tokens


def test_checkpoint_is_written_for_every_mission(runtime):
    supervisor = Supervisor(runtime)
    mission_id, _spec, _result = supervisor.start("задача с чекпоинтом")

    snapshot = runtime.checkpointer.load(mission_id)
    assert snapshot is not None
    assert snapshot["mission"]["id"] == mission_id
    assert "counts" in snapshot
    assert snapshot["dod"], "критерии приёмки должны попадать в снимок"


def test_resume_pointer_lists_only_unfinished_work(runtime):
    """Контракт с агент-хостом: завершённая миссия не зовёт его обратно."""
    supervisor = Supervisor(runtime)
    finished_id, _spec, _result = supervisor.start("задача, которая закроется")

    pointer = runtime.checkpointer.resume_pointer()
    assert all(m["mission_id"] != finished_id for m in pointer["missions"])

    # Незавершённая миссия, наоборот, обязана быть в указателе.
    unfinished_id = runtime.sm.create_mission("миссия, которую не доводили")
    runtime.sm.add_task(unfinished_id, title="работа", role="coder")
    pointer = runtime.checkpointer.refresh_resume_pointer()

    assert pointer["has_work"] is True
    assert any(m["mission_id"] == unfinished_id for m in pointer["missions"])


def test_memory_is_consolidated_after_success(runtime):
    """Система должна выносить из прогона знание, иначе учиться нечему."""
    from agentos.orchestrator.improve import Improver

    supervisor = Supervisor(runtime)
    mission_id, _spec, _result = supervisor.start("задача для консолидации")

    result = Improver(runtime).consolidate(mission_id)
    assert result.facts or result.lessons
    assert runtime.semantic.stats()
