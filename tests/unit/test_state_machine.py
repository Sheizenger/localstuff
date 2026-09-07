"""Машина состояний: на ней держится корректность resume."""

from __future__ import annotations

import time

import pytest

from agentos.errors import InvalidTransition
from agentos.state.machine import TASK_TRANSITIONS, MissionStatus, TaskStatus


def test_dependent_task_waits_and_then_becomes_ready(sm):
    mission = sm.create_mission("цель")
    first = sm.add_task(mission, title="A", role="researcher")
    second = sm.add_task(mission, title="B", role="coder", depends_on=[first])

    assert sm.get_task(first).status is TaskStatus.READY
    assert sm.get_task(second).status is TaskStatus.PENDING

    sm.transition(first, TaskStatus.RUNNING)
    sm.transition(first, TaskStatus.DONE, result="готово")

    assert sm.get_task(second).status is TaskStatus.READY


def test_done_is_terminal(sm):
    mission = sm.create_mission("цель")
    task = sm.add_task(mission, title="A", role="coder")
    sm.transition(task, TaskStatus.RUNNING)
    sm.transition(task, TaskStatus.DONE)

    with pytest.raises(InvalidTransition):
        sm.transition(task, TaskStatus.READY)


def test_every_status_has_a_transition_rule():
    """Забытый статус в таблице переходов — источник немых багов."""
    for status in TaskStatus:
        assert status in TASK_TRANSITIONS


def test_idempotency_key_prevents_duplicates(sm):
    """Повторное планирование после краша не должно плодить задачи."""
    mission = sm.create_mission("цель")
    first = sm.add_task(mission, title="A", role="coder", idempotency_key="k")
    second = sm.add_task(mission, title="A", role="coder", idempotency_key="k")
    assert first == second
    assert len(sm.tasks_of(mission)) == 1


def test_claim_is_exclusive(sm):
    mission = sm.create_mission("цель")
    sm.add_task(mission, title="единственная", role="coder")

    first = sm.claim_next(mission)
    second = sm.claim_next(mission)

    assert first is not None
    assert first.status is TaskStatus.RUNNING
    assert second is None, "одну задачу нельзя выдать двум исполнителям"


def test_parallel_claims_do_not_overlap(sm):
    """Планировщик исполняет ветки в потоках — захват должен быть атомарным."""
    import threading

    mission = sm.create_mission("цель")
    for index in range(20):
        sm.add_task(mission, title=f"T{index}", role="coder")

    claimed: list[str] = []
    lock = threading.Lock()

    def worker():
        while True:
            task = sm.claim_next(mission)
            if task is None:
                return
            with lock:
                claimed.append(task.id)
            sm.transition(task.id, TaskStatus.DONE)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(claimed) == 20
    assert len(set(claimed)) == 20


def test_quota_block_resumes_when_window_passes(sm):
    mission = sm.create_mission("цель")
    task = sm.add_task(mission, title="A", role="coder")
    sm.transition(task, TaskStatus.RUNNING)
    sm.transition(
        task, TaskStatus.BLOCKED_QUOTA, blocked_reason="лимит", resume_after=time.time() - 1
    )

    assert sm.next_resume_at(mission) is not None
    assert sm.unblock_due() == 1
    assert sm.get_task(task).status is TaskStatus.READY


def test_stale_running_returns_to_queue(sm):
    """Убитая сессия не должна оставлять вечно «выполняющуюся» задачу."""
    mission = sm.create_mission("цель")
    task = sm.add_task(mission, title="A", role="coder")
    sm.claim_next(mission)

    assert sm.release_stale_running(older_than_s=-1) == 1
    assert sm.get_task(task).status is TaskStatus.READY


def test_mission_settled_only_when_nothing_can_move(sm):
    mission = sm.create_mission("цель")
    task = sm.add_task(mission, title="A", role="coder")
    assert not sm.is_mission_settled(mission)

    sm.transition(task, TaskStatus.RUNNING)
    sm.transition(task, TaskStatus.DONE)
    assert sm.is_mission_settled(mission)

    sm.set_mission_status(mission, MissionStatus.DONE)
    assert sm.get_mission(mission)["status"] == MissionStatus.DONE.value
