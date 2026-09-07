"""Супервизор — то, что доводит миссию до конца без напоминаний.

Его цикл: спланировать -> исполнить -> проверить -> исправить -> закрыть.
Он же отвечает за продолжение работы: после обрыва сессии или сброса
лимитов достаточно вызвать resume(), и система сама вспомнит, на чём
остановилась, — состояние живёт в БД и чекпоинтах, а не в контексте чата.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..bus import EV_MISSION_STATUS, EV_RESUME
from ..runtime import MODE_NATIVE, Runtime
from ..state.machine import NEEDS_HUMAN, MissionStatus, TaskStatus
from .critic import Critic
from .intake import Intake, MissionSpec
from .planner import Planner
from .scheduler import Scheduler, TickResult

#: Коды выхода для скриптов запуска (см. scripts/headless.sh).
EXIT_NOTHING_TO_DO = 0
EXIT_NEEDS_HUMAN = 10
EXIT_WAITING_QUOTA = 75
EXIT_IN_PROGRESS = 1


@dataclass
class AdvanceResult:
    """Что произошло за один заход по миссии."""

    mission_id: str
    tick: TickResult = field(default_factory=TickResult)
    verdict: str = ""
    status: str = ""
    needs_human: list[str] = field(default_factory=list)
    wait_seconds: int = 0
    handoffs: list[dict[str, str]] = field(default_factory=list)

    @property
    def finished(self) -> bool:
        return self.status in (MissionStatus.DONE.value, MissionStatus.FAILED.value)


class Supervisor:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime
        self.intake = Intake(runtime)
        self.planner = Planner(runtime)
        self.scheduler = Scheduler(runtime)
        self.critic = Critic(runtime)

    # ---------------------------------------------------------------- запуск
    def start(
        self, goal: str, *, context: str = "", budget_tokens: int = 0, budget_usd: float = 0.0
    ) -> tuple[str, MissionSpec, AdvanceResult]:
        """Принять цель и сразу начать работу."""
        mission_id, spec = self.intake.create(
            goal, context=context, budget_tokens=budget_tokens, budget_usd=budget_usd
        )
        return mission_id, spec, self.advance(mission_id)

    # -------------------------------------------------------------- движение
    def advance(
        self,
        mission_id: str,
        *,
        max_ticks: int = 50,
        host_verdict: Any = None,
    ) -> AdvanceResult:
        """Продвинуть миссию настолько, насколько это возможно сейчас."""
        result = AdvanceResult(mission_id=mission_id)
        mission = self.rt.sm.get_mission(mission_id)
        if not mission:
            result.status = "not_found"
            return result

        if not self.rt.sm.tasks_of(mission_id):
            self.planner.persist(mission_id, self.planner.build(mission_id))

        result.tick = self.scheduler.run(mission_id, max_ticks=max_ticks)
        result.handoffs = result.tick.handoffs

        # Задачи кончились — пора проверять результат.
        if self.rt.sm.is_mission_settled(mission_id) and not result.handoffs:
            result = self._verify_stage(mission_id, result, host_verdict=host_verdict)

        self.rt.checkpointer.settle_missions()
        self.rt.checkpointer.write(mission_id)

        refreshed = self.rt.sm.get_mission(mission_id) or {}
        result.status = refreshed.get("status", "")
        result.needs_human = self._needs_human(mission_id)
        result.wait_seconds = self.scheduler.wait_seconds(mission_id)
        return result

    def _verify_stage(
        self, mission_id: str, result: AdvanceResult, *, host_verdict: Any = None
    ) -> AdvanceResult:
        """Прогнать гейты и критика; при отказе — доработать и вернуться."""
        counts = self.rt.sm.status_counts(mission_id)
        if not counts.get(TaskStatus.DONE.value):
            return result  # нечего проверять
        if any(counts.get(s.value, 0) for s in NEEDS_HUMAN):
            return result  # сначала снять блокировки, потом судить о результате

        self.rt.sm.set_mission_status(mission_id, MissionStatus.VERIFYING)
        verification = self.critic.verify(mission_id, host_verdict=host_verdict)
        result.verdict = verification.verdict.verdict

        if verification.fix_tasks:
            # Появились задачи на исправление — доводим их в этом же заходе.
            follow_up = self.scheduler.run(mission_id)
            result.tick.executed += follow_up.executed
            result.tick.done += follow_up.done
            result.tick.blocked += follow_up.blocked
            result.tick.failed += follow_up.failed
            result.handoffs += follow_up.handoffs
            if self.rt.sm.is_mission_settled(mission_id) and not follow_up.handoffs:
                verification = self.critic.verify(mission_id)
                result.verdict = verification.verdict.verdict

        if verification.accepted:
            self.rt.sm.set_mission_status(mission_id, MissionStatus.DONE)
            self._on_finish(mission_id)
        elif verification.verdict.verdict == "reject" and not verification.fix_tasks:
            # Исправления исчерпаны, результат так и не принят.
            self._on_finish(mission_id, success=False)
            self.rt.sm.set_mission_status(
                mission_id,
                MissionStatus.BLOCKED,
                blocked_reason="; ".join(verification.verdict.reasons)[:400]
                or "результат не принят, попытки исправления исчерпаны",
            )
        elif verification.verdict.verdict == "needs_human":
            self.rt.sm.set_mission_status(
                mission_id,
                MissionStatus.BLOCKED,
                blocked_reason="; ".join(verification.verdict.reasons)[:400]
                or "критик просит участия человека",
            )
        self.rt.bus.emit(
            EV_MISSION_STATUS,
            mission_id=mission_id,
            actor="supervisor",
            verdict=result.verdict,
            summary=verification.verdict.render()[:400],
        )
        return result

    def _on_finish(self, mission_id: str, *, success: bool = True) -> None:
        """Консолидация памяти после завершения миссии.

        Вызывается и при провале: неудачный прогон — тоже знание, а навыки
        должны узнать, что они не помогли.
        """
        if not self.rt.config.get("memory.consolidate.on_run_finish", True):
            return
        from .improve import Improver

        improver = Improver(self.rt)
        improver.consolidate(mission_id, success=success)
        improver.retro(mission_id)

    # ------------------------------------------------------------- resume
    def resume(self, *, once: bool = False) -> tuple[int, list[AdvanceResult]]:
        """Подхватить всё незавершённое. Возвращает код выхода и отчёты.

        Именно эту функцию вызывает SessionStart-хук и `make resume`:
        человеку не нужно объяснять системе, где она остановилась.
        """
        self.rt.sync_skills()
        cleared = self.rt.quota.sweep()
        unblocked = self.rt.sm.unblock_due()
        missions = self.rt.sm.active_missions()
        if not missions:
            self.rt.checkpointer.refresh_resume_pointer()
            return EXIT_NOTHING_TO_DO, []

        self.rt.bus.emit(
            EV_RESUME,
            actor="supervisor",
            missions=len(missions),
            quota_cleared=cleared,
            tasks_unblocked=unblocked,
        )

        results = [self.advance(m["id"], max_ticks=1 if once else 50) for m in missions]
        self.rt.checkpointer.refresh_resume_pointer()

        if any(r.needs_human for r in results):
            return EXIT_NEEDS_HUMAN, results
        if any(r.handoffs for r in results):
            return EXIT_IN_PROGRESS, results
        pending = [r for r in results if not r.finished]
        if not pending:
            return EXIT_NOTHING_TO_DO, results
        if all(r.wait_seconds > 0 for r in pending):
            return EXIT_WAITING_QUOTA, results
        return EXIT_IN_PROGRESS, results

    # -------------------------------------------------------------- сводки
    def _needs_human(self, mission_id: str) -> list[str]:
        rows = self.rt.store.query(
            "SELECT title, status, blocked_reason FROM tasks WHERE mission_id=?"
            " AND status IN (?,?)",
            (
                mission_id,
                TaskStatus.BLOCKED_APPROVAL.value,
                TaskStatus.BLOCKED_CAPABILITY.value,
            ),
        )
        return [f"{r['title']} — {r['blocked_reason']}" for r in rows]

    def announce(self) -> str:
        """Одна строка о состоянии дел — печатается на старте сессии.

        Одна: длинный отчёт на каждом старте съедал бы контекст, ради
        экономии которого построена вся система.
        """
        pointer = self.rt.checkpointer.resume_pointer()
        missions = pointer.get("missions", [])
        if not missions:
            return "AgentOS: незавершённых миссий нет."
        parts = []
        for entry in missions:
            counts = entry.get("counts", {})
            done = counts.get("DONE", 0)
            total = sum(counts.values()) or 0
            tail = ""
            if entry.get("needs_human"):
                tail = f", ждёт человека: {entry['needs_human']}"
            elif entry.get("resume_at"):
                wait = max(0, int(entry["resume_at"] - time.time()))
                tail = f", продолжит через {wait}s"
            parts.append(f"{entry['goal'][:60]} [{done}/{total}{tail}]")
        return "AgentOS подхватил: " + "; ".join(parts)

    def digest(self, mission_id: str = "") -> dict[str, Any]:
        """Машиночитаемая сводка для `agentctl status`."""
        missions = (
            [self.rt.sm.get_mission(mission_id)]
            if mission_id
            else self.rt.sm.active_missions()
        )
        out: list[dict[str, Any]] = []
        for mission in [m for m in missions if m]:
            mid = mission["id"]
            spend = self.rt.ledger.mission_spend(mid)
            out.append(
                {
                    "mission_id": mid,
                    "goal": mission["goal"],
                    "status": mission["status"],
                    "counts": self.rt.sm.status_counts(mid),
                    "tokens": spend.tokens,
                    "usd": round(spend.usd, 4),
                    "budget_tokens": spend.budget_tokens,
                    "needs_human": self._needs_human(mid),
                    "wait_seconds": self.scheduler.wait_seconds(mid),
                    "mode": self.rt.mode,
                }
            )
        return {"missions": out, "mode": self.rt.mode, "native": self.rt.mode == MODE_NATIVE}
