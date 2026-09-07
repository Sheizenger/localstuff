"""То, что требует решения человека: подтверждения и бюджет.

Раньше оба контура были разомкнуты: запросы на подтверждение никуда не
складывались, а исчерпанный бюджет был тупиком — поднять его было нечем.
"""

from __future__ import annotations

from agentos.state.approvals import STATUS_DENIED, STATUS_GRANTED
from agentos.state.machine import MissionStatus, TaskStatus


def _blocked_on_approval(runtime) -> tuple[str, str, str]:
    mission_id = runtime.sm.create_mission("миссия с необратимым действием")
    task_id = runtime.sm.add_task(mission_id, title="запушить ветку", role="ops")
    runtime.sm.transition(task_id, TaskStatus.RUNNING)
    runtime.sm.transition(
        task_id, TaskStatus.BLOCKED_APPROVAL, blocked_reason="git_push: нужно подтверждение"
    )
    approval_id = runtime.approvals.request(
        "git_push", "нужно подтверждение на пуш", mission_id=mission_id, task_id=task_id
    )
    return mission_id, task_id, approval_id


def test_approval_request_is_queued_not_only_a_task_status(runtime):
    mission_id, task_id, approval_id = _blocked_on_approval(runtime)

    pending = runtime.approvals.pending(mission_id)

    assert [a.id for a in pending] == [approval_id]
    assert pending[0].action == "git_push"
    assert pending[0].task_id == task_id


def test_repeated_request_does_not_duplicate(runtime):
    """Повторные попытки задачи не должны множить один и тот же вопрос."""
    mission_id, task_id, approval_id = _blocked_on_approval(runtime)

    again = runtime.approvals.request(
        "git_push", "нужно подтверждение на пуш", mission_id=mission_id, task_id=task_id
    )

    assert again == approval_id
    assert len(runtime.approvals.pending(mission_id)) == 1


def test_granting_returns_the_task_to_the_queue(runtime):
    _mission_id, task_id, approval_id = _blocked_on_approval(runtime)

    decided = runtime.approvals.decide(approval_id, granted=True)
    runtime.sm.transition(task_id, TaskStatus.READY, blocked_reason="")

    assert decided.status == STATUS_GRANTED
    assert runtime.sm.get_task(task_id).status is TaskStatus.READY
    assert not runtime.approvals.pending()


def test_denial_is_recorded(runtime):
    _mission_id, _task_id, approval_id = _blocked_on_approval(runtime)

    decided = runtime.approvals.decide(approval_id, granted=False)

    assert decided.status == STATUS_DENIED
    assert not runtime.approvals.pending()


def test_scheduler_queues_approval_when_a_task_blocks(runtime):
    """Запрос должен появляться сам, а не только руками в тесте."""
    from agentos.orchestrator.dispatch import STATUS_BLOCKED_APPROVAL, DispatchOutcome
    from agentos.orchestrator.scheduler import Scheduler, TickResult

    mission_id = runtime.sm.create_mission("миссия с подтверждением")
    task_id = runtime.sm.add_task(mission_id, title="опасное", role="ops")
    task = runtime.sm.claim_next(mission_id)

    Scheduler(runtime)._apply(
        task,
        DispatchOutcome(status=STATUS_BLOCKED_APPROVAL, detail="git_push: нужен человек"),
        TickResult(),
    )

    pending = runtime.approvals.pending(mission_id)
    assert pending, "блокировка на подтверждении обязана попадать в очередь"
    assert pending[0].task_id == task_id
    assert runtime.sm.get_task(task_id).status is TaskStatus.BLOCKED_APPROVAL


def test_budget_can_be_raised_and_mission_unblocked(runtime):
    mission_id = runtime.sm.create_mission("миссия с бюджетом", budget_tokens=1000)
    runtime.ledger.record(
        provider="mock", model="mock-small", tokens_in=900, tokens_out=200, mission_id=mission_id
    )
    assert runtime.ledger.mission_spend(mission_id).exhausted

    runtime.sm.set_mission_status(
        mission_id, MissionStatus.BLOCKED, blocked_reason="бюджет миссии исчерпан"
    )
    with runtime.store.tx() as conn:
        conn.execute("UPDATE missions SET budget_tokens=? WHERE id=?", (50_000, mission_id))
    runtime.sm.set_mission_status(mission_id, MissionStatus.RUNNING)

    spend = runtime.ledger.mission_spend(mission_id)
    assert not spend.exhausted
    assert spend.tokens_left > 0
    assert runtime.sm.get_mission(mission_id)["status"] == MissionStatus.RUNNING.value
