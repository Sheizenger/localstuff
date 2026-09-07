"""Планировщик исполнения: кто и когда работает.

Три ограничителя, в порядке важности:
  1. зависимости DAG — задача не стартует, пока не готовы предшественники;
  2. бюджет миссии — при исчерпании работа встаёт, а не «доедает» лимит;
  3. параллелизм — не больше max_concurrency задач одновременно.

Блокировка одной ветки (квота, доступ, подтверждение) не останавливает
остальные: это прямое требование к автономности.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from ..bus import EV_TASK_BLOCKED, EV_TASK_FAILED, EV_TASK_FINISHED
from ..runtime import Runtime
from ..state.machine import MissionStatus, Task, TaskStatus
from .dispatch import (
    STATUS_BLOCKED_APPROVAL,
    STATUS_BLOCKED_CAPABILITY,
    STATUS_BLOCKED_QUOTA,
    STATUS_DONE,
    STATUS_HANDOFF,
    Dispatcher,
    DispatchOutcome,
    outcome_to_result_text,
)


@dataclass
class TickResult:
    """Итог одного прохода планировщика."""

    executed: int = 0
    done: int = 0
    blocked: int = 0
    failed: int = 0
    handoffs: list[dict[str, str]] = field(default_factory=list)
    stopped_reason: str = ""

    @property
    def progressed(self) -> bool:
        return self.executed > 0


def _approval_action(detail: str) -> str:
    """Вытащить имя действия из текста блокировки для читаемого списка."""
    head = detail.split(":", 1)[0].strip()
    return head[:60] or "подтверждение"


class Scheduler:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime
        self.dispatcher = Dispatcher(runtime)

    # ------------------------------------------------------------------ цикл
    def run(self, mission_id: str, *, max_ticks: int = 100) -> TickResult:
        """Крутить проходы, пока есть готовая работа."""
        total = TickResult()
        for _ in range(max_ticks):
            tick = self.tick(mission_id)
            total.executed += tick.executed
            total.done += tick.done
            total.blocked += tick.blocked
            total.failed += tick.failed
            total.handoffs += tick.handoffs
            if tick.stopped_reason:
                total.stopped_reason = tick.stopped_reason
                break
            if tick.handoffs:
                # Дальше двигать нечего: ждём, пока агент-хост вернёт
                # результаты через `agentctl task report`.
                break
            if not tick.progressed:
                break
        self.rt.checkpointer.write(mission_id)
        return total

    def tick(self, mission_id: str) -> TickResult:
        """Один проход: взять готовые задачи и выполнить их параллельно."""
        result = TickResult()
        mission = self.rt.sm.get_mission(mission_id)
        if not mission:
            result.stopped_reason = "миссия не найдена"
            return result

        # Освободить зависшие RUNNING: сессия могла оборваться посреди работы.
        stale_after = float(self.rt.config.get("runtime.step_timeout_s", 900)) * 2
        self.rt.sm.release_stale_running(stale_after)
        # Снять блокировки, у которых истёк срок ожидания квоты.
        self.rt.sm.unblock_due()
        self.rt.quota.sweep()

        spend = self.rt.ledger.mission_spend(mission_id)
        if spend.exhausted:
            self.rt.sm.set_mission_status(
                mission_id,
                MissionStatus.BLOCKED,
                blocked_reason=f"бюджет миссии исчерпан ({spend.tokens} токенов,"
                f" ${spend.usd:.2f}) — подтверди увеличение",
            )
            result.stopped_reason = "бюджет исчерпан"
            return result

        batch = self._claim_batch(mission_id)
        if not batch:
            return result

        self.rt.sm.set_mission_status(mission_id, MissionStatus.RUNNING)

        if len(batch) == 1:
            outcomes = [(batch[0], self._safe_execute(batch[0], mission))]
        else:
            outcomes = self._execute_parallel(batch, mission)

        for task, outcome in outcomes:
            result.executed += 1
            self._apply(task, outcome, result)

        self.rt.checkpointer.write(mission_id)
        return result

    # -------------------------------------------------------------- выборка
    def _claim_batch(self, mission_id: str) -> list[Task]:
        """Взять пачку задач под лимит параллелизма."""
        limit = max(1, int(self.rt.config.get("runtime.max_concurrency", 4)))
        batch: list[Task] = []
        for _ in range(limit):
            task = self.rt.sm.claim_next(mission_id)
            if task is None:
                break
            batch.append(task)
        return batch

    def _execute_parallel(
        self, batch: list[Task], mission: dict[str, Any]
    ) -> list[tuple[Task, DispatchOutcome]]:
        outcomes: list[tuple[Task, DispatchOutcome]] = []
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = {pool.submit(self._safe_execute, t, mission): t for t in batch}
            for future in as_completed(futures):
                outcomes.append((futures[future], future.result()))
        return outcomes

    def _safe_execute(self, task: Task, mission: dict[str, Any]) -> DispatchOutcome:
        try:
            return self.dispatcher.execute(task, mission)
        except Exception as exc:  # исполнитель не должен ронять планировщик
            return DispatchOutcome(
                status="failed", detail=f"{type(exc).__name__}: {exc}"
            )

    # ------------------------------------------------------- применение итога
    def _apply(self, task: Task, outcome: DispatchOutcome, result: TickResult) -> None:
        report_limit = int(self.rt.config.get("budget.subagent_report_tokens", 1200))
        text = outcome_to_result_text(outcome, report_limit)

        if outcome.status == STATUS_DONE:
            self.rt.sm.transition(
                task.id,
                TaskStatus.DONE,
                result=text,
                provider=outcome.provider,
                model=outcome.model,
            )
            self.rt.bus.emit(
                EV_TASK_FINISHED,
                mission_id=task.mission_id,
                task_id=task.id,
                actor=task.role,
                summary=(outcome.report.summary if outcome.report else "")[:400],
                tokens=outcome.tokens,
                usd=round(outcome.usd, 6),
            )
            result.done += 1
            return

        if outcome.status == STATUS_HANDOFF:
            # Задача остаётся RUNNING: её закроет агент-хост через
            # `agentctl task report`. Здесь мы только отдаём бриф.
            result.handoffs.append(
                {"task_id": task.id, "title": task.title, "brief_path": outcome.brief_path}
            )
            return

        blocked_map = {
            STATUS_BLOCKED_QUOTA: TaskStatus.BLOCKED_QUOTA,
            STATUS_BLOCKED_CAPABILITY: TaskStatus.BLOCKED_CAPABILITY,
            STATUS_BLOCKED_APPROVAL: TaskStatus.BLOCKED_APPROVAL,
        }
        if outcome.status == STATUS_BLOCKED_APPROVAL:
            # Запрос живёт в очереди, а не только в статусе задачи: иначе
            # список того, что нужно от человека, теряется между сессиями.
            self.rt.approvals.request(
                _approval_action(outcome.detail),
                outcome.detail,
                mission_id=task.mission_id,
                task_id=task.id,
            )

        if outcome.status in blocked_map:
            self.rt.sm.transition(
                task.id,
                blocked_map[outcome.status],
                blocked_reason=outcome.detail,
                resume_after=outcome.resume_after,
                provider=outcome.provider,
                model=outcome.model,
            )
            self.rt.bus.emit(
                EV_TASK_BLOCKED,
                mission_id=task.mission_id,
                task_id=task.id,
                actor=task.role,
                reason=outcome.detail,
                block_kind=outcome.status,
                resume_after=outcome.resume_after,
            )
            result.blocked += 1
            return

        # Провал: пока есть попытки — задача возвращается в очередь.
        max_attempts = int(self.rt.config.get("runtime.max_task_attempts", 3))
        if task.attempts < max_attempts:
            self.rt.sm.transition(
                task.id, TaskStatus.READY, blocked_reason=outcome.detail
            )
            self.rt.bus.emit(
                EV_TASK_FAILED,
                mission_id=task.mission_id,
                task_id=task.id,
                actor=task.role,
                reason=outcome.detail,
                attempt=task.attempts,
                retry=True,
            )
        else:
            self.rt.sm.transition(task.id, TaskStatus.FAILED, result=text,
                                  blocked_reason=outcome.detail)
            self.rt.bus.emit(
                EV_TASK_FAILED,
                mission_id=task.mission_id,
                task_id=task.id,
                actor=task.role,
                reason=outcome.detail,
                attempt=task.attempts,
                retry=False,
            )
            result.failed += 1

    # ------------------------------------------------------------ информация
    def next_resume_at(self, mission_id: str) -> float | None:
        task_reset = self.rt.sm.next_resume_at(mission_id)
        quota_reset = self.rt.quota.next_reset()
        candidates = [t for t in (task_reset, quota_reset) if t]
        return min(candidates) if candidates else None

    def wait_seconds(self, mission_id: str) -> int:
        moment = self.next_resume_at(mission_id)
        return max(0, int(moment - time.time())) if moment else 0
