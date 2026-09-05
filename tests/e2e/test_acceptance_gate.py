"""Приёмка: миссия не может стать DONE с неподтверждёнными критериями.

Это регрессионный тест на найденный дефект: раньше вердикт критика молча
перезаписывался пересчётом статуса по задачам, и миссия закрывалась как
готовая, хотя семантический критерий никто не проверял.
"""

from __future__ import annotations

from agentos.agents.report import Verdict
from agentos.orchestrator.critic import Critic
from agentos.orchestrator.intake import Intake
from agentos.orchestrator.supervisor import Supervisor
from agentos.state.machine import MissionStatus, TaskStatus


def _finish_all_tasks(runtime, mission_id: str) -> None:
    for task in runtime.sm.tasks_of(mission_id):
        if task.status is TaskStatus.DONE:
            continue
        if task.status is TaskStatus.PENDING:
            runtime.sm.transition(task.id, TaskStatus.READY)
        if runtime.sm.get_task(task.id).status is TaskStatus.READY:
            runtime.sm.transition(task.id, TaskStatus.RUNNING)
        runtime.sm.transition(task.id, TaskStatus.DONE, result="сделано")


def test_mission_stays_blocked_while_criteria_are_unconfirmed(runtime):
    mission_id, _spec = Intake(runtime).create("цель без подтверждения")
    task_id = runtime.sm.add_task(mission_id, title="работа", role="coder")
    runtime.sm.transition(task_id, TaskStatus.RUNNING)
    runtime.sm.transition(task_id, TaskStatus.DONE, result="готово")

    # Задач не осталось, но критерии никто не подтверждал.
    changed = runtime.checkpointer.settle_missions()

    assert mission_id in changed
    mission = runtime.sm.get_mission(mission_id)
    assert mission["status"] == MissionStatus.BLOCKED.value
    assert "критерии приёмки" in mission["blocked_reason"]
    assert runtime.checkpointer.unmet_criteria(mission_id)


def test_host_verdict_closes_the_mission(runtime):
    """В native-режиме своей модели нет — вердикт выносит агент-хост."""
    mission_id, _spec = Intake(runtime).create("цель с вердиктом хоста")
    _finish_all_tasks(runtime, mission_id)
    runtime.sm.add_task(mission_id, title="работа", role="coder")
    _finish_all_tasks(runtime, mission_id)

    result = Critic(runtime).verify(
        mission_id, host_verdict=Verdict(verdict="accept", reasons=["проверено хостом"])
    )
    runtime.checkpointer.settle_missions()

    assert result.accepted
    assert not runtime.checkpointer.unmet_criteria(mission_id)
    assert runtime.sm.get_mission(mission_id)["status"] == MissionStatus.DONE.value


def test_red_gate_overrides_host_accept(runtime, monkeypatch):
    """Иначе программный гейт перестаёт быть гейтом."""
    from agentos.orchestrator.critic import IN_GATE_ENV

    # Миссия собирается без Intake: нужен ровно один гейт — заведомо красный
    # и не запускающий тесты, иначе прогон уйдёт в рекурсию.
    mission_id = runtime.sm.create_mission("цель с красным гейтом")
    Intake(runtime).add_criterion(
        mission_id, "заведомо красный", kind="programmatic", cmd="false"
    )
    task_id = runtime.sm.add_task(mission_id, title="работа", role="coder")
    runtime.sm.transition(task_id, TaskStatus.RUNNING)
    runtime.sm.transition(task_id, TaskStatus.DONE, result="сделано")
    monkeypatch.delenv(IN_GATE_ENV, raising=False)

    result = Critic(runtime).verify(
        mission_id, host_verdict=Verdict(verdict="accept", reasons=["мне кажется, всё хорошо"])
    )

    assert not result.accepted
    assert result.verdict.verdict == "reject"
    assert any("красный гейт" in reason for reason in result.verdict.reasons)
    assert runtime.sm.get_mission(mission_id)["status"] != MissionStatus.DONE.value


def test_failed_task_makes_the_mission_failed_not_done(runtime):
    mission_id, _spec = Intake(runtime).create("цель с провалом")
    task_id = runtime.sm.add_task(mission_id, title="провальная", role="coder")
    runtime.sm.transition(task_id, TaskStatus.RUNNING)
    runtime.sm.transition(task_id, TaskStatus.FAILED, blocked_reason="не вышло")

    runtime.checkpointer.settle_missions()

    assert runtime.sm.get_mission(mission_id)["status"] == MissionStatus.FAILED.value


def test_supervisor_does_not_report_done_without_verification(runtime):
    """Сквозная проверка того же инварианта через обычный запуск миссии."""
    mission_id, _spec, result = Supervisor(runtime).start("обычная миссия")

    mission = runtime.sm.get_mission(mission_id)
    if mission["status"] == MissionStatus.DONE.value:
        assert not runtime.checkpointer.unmet_criteria(mission_id), (
            "DONE только при подтверждённых критериях"
        )
    else:
        assert result.verdict or mission["blocked_reason"]
