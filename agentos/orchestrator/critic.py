"""Самопроверка: программные гейты + критик на другой модели.

Порядок принципиальный. Сначала выполняются программные гейты (тесты,
линт) — их результат не обсуждается: красный гейт означает reject
независимо от того, что скажет модель. Только потом семантические
критерии проверяет критик, по возможности у другого провайдера, чем тот,
что делал работу: модель одного семейства склонна соглашаться сама с собой.

Отклонённый результат не эскалируется человеку сразу — система заводит
задачи на исправление и пробует довести работу сама.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from ..agents.report import Verdict
from ..bus import EV_CRITIC_VERDICT, EV_GATE_RESULT
from ..errors import ProviderUnavailable, QuotaExhausted
from ..memory.working import GOAL_MARKER, SCHEMA_MARKER, truncate_to_tokens
from ..providers.base import Message
from ..runtime import Runtime
from ..tools.shell import run_command

#: Сколько попыток исправления допускается до эскалации человеку.
MAX_FIX_ROUNDS = 2

#: Метка «мы уже внутри программного гейта». Гейт обычно запускает тесты,
#: а тесты могут запускать миссию — без этой метки получается бесконечная
#: рекурсия make test -> pytest -> миссия -> make test.
IN_GATE_ENV = "AGENTOS_IN_GATE"


@dataclass
class GateResult:
    name: str
    cmd: str
    passed: bool
    output: str = ""
    #: Гейт не запускался (вложенный запуск). Пропуск — не доказательство:
    #: такой критерий не считается ни пройденным, ни проваленным.
    skipped: bool = False


@dataclass
class VerificationResult:
    verdict: Verdict
    gates: list[GateResult] = field(default_factory=list)
    fix_tasks: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.verdict.accepted and all(g.passed or g.skipped for g in self.gates)


class Critic:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    # ------------------------------------------------------------ гейты
    def run_gates(self, mission_id: str) -> list[GateResult]:
        """Прогнать программные критерии приёмки."""
        rows = self.rt.store.query(
            "SELECT id, criterion, cmd FROM dod WHERE mission_id=? AND kind='programmatic'"
            " AND cmd != '' ORDER BY ord",
            (mission_id,),
        )
        nested = os.environ.get(IN_GATE_ENV) == "1"
        results: list[GateResult] = []
        for row in rows:
            if nested:
                # Мы уже выполняемся внутри гейта: повторный запуск зациклится.
                note = "пропущен: выполняется внутри другого программного гейта"
                results.append(GateResult(row["criterion"], row["cmd"], True, note, skipped=True))
                with self.rt.store.tx() as conn:
                    conn.execute(
                        "UPDATE dod SET status=?, evidence=?, updated_at=? WHERE id=?",
                        ("skipped", note, time.time(), row["id"]),
                    )
                continue
            outcome = run_command(
                row["cmd"],
                self.rt.guard,
                self.rt.config.root,
                env={IN_GATE_ENV: "1"},
            )
            passed = outcome.ok
            tail = (outcome.output or outcome.error)[-2000:]
            results.append(GateResult(row["criterion"], row["cmd"], passed, tail))
            with self.rt.store.tx() as conn:
                conn.execute(
                    "UPDATE dod SET status=?, evidence=?, updated_at=? WHERE id=?",
                    ("pass" if passed else "fail", tail, time.time(), row["id"]),
                )
            self.rt.bus.emit(
                EV_GATE_RESULT,
                mission_id=mission_id,
                actor="critic",
                gate=row["criterion"],
                cmd=row["cmd"],
                passed=passed,
                summary=("гейт зелёный" if passed else f"ГЕЙТ ПРОВАЛЕН: {row['cmd']}"),
                output=tail[-800:],
            )
        return results

    # ------------------------------------------------------------ проверка
    def verify(
        self, mission_id: str, *, host_verdict: Verdict | None = None
    ) -> VerificationResult:
        """Проверить миссию против DoD и, при отказе, завести исправления.

        host_verdict — вердикт, вынесенный агент-хостом. Он нужен в
        native-режиме: своей модели у системы там нет, а без вердикта миссия
        никогда не закроется. Красный программный гейт отменяет любой
        вердикт, чей бы он ни был: иначе гейт перестаёт быть гейтом.
        """
        gates = self.run_gates(mission_id)
        failed_gates = [g for g in gates if not g.passed and not g.skipped]

        if failed_gates:
            verdict = Verdict(
                verdict="reject",
                reasons=[f"красный гейт: {g.cmd}" for g in failed_gates],
                next_actions=[f"починить: {g.cmd}" for g in failed_gates],
            )
        elif host_verdict is not None:
            verdict = host_verdict
        else:
            verdict = self._ask_critic(mission_id, gates)

        self.rt.bus.emit(
            EV_CRITIC_VERDICT,
            mission_id=mission_id,
            actor="critic",
            verdict=verdict.verdict,
            summary=verdict.render()[:600],
            gates_failed=len(failed_gates),
            source="host" if host_verdict is not None and not failed_gates else "critic",
        )
        self._record_semantic_criteria(mission_id, verdict)

        fix_tasks: list[str] = []
        if verdict.verdict == "reject":
            fix_tasks = self._spawn_fixes(mission_id, verdict)
        return VerificationResult(verdict=verdict, gates=gates, fix_tasks=fix_tasks)

    # ------------------------------------------------------------- внутреннее
    def _ask_critic(self, mission_id: str, gates: list[GateResult]) -> Verdict:
        mission = self.rt.sm.get_mission(mission_id) or {}
        criteria = self.rt.store.query(
            "SELECT criterion, kind, status FROM dod WHERE mission_id=? ORDER BY ord",
            (mission_id,),
        )
        semantic = [c for c in criteria if c["kind"] != "programmatic"]
        if not semantic:
            return Verdict(verdict="accept")

        role = self.rt.config.role("critic")
        producer = str(
            self.rt.store.scalar(
                "SELECT provider FROM tasks WHERE mission_id=? AND provider != ''"
                " ORDER BY finished_at DESC LIMIT 1",
                (mission_id,),
                "",
            )
            or ""
        )
        try:
            route = self.rt.router.critic_route(role.tier, producer)
        except (QuotaExhausted, ProviderUnavailable) as exc:
            # Без критика результат не объявляется готовым — только needs_human.
            return Verdict(
                verdict="needs_human",
                reasons=[f"критик недоступен: {exc}"],
                next_actions=["проверить результат вручную или дождаться сброса лимитов"],
            )

        evidence = self._collect_evidence(mission_id)
        prompt = (
            f"{GOAL_MARKER} {mission.get('goal', '')}\n\n"
            "КРИТЕРИИ ПРИЁМКИ:\n"
            + "\n".join(f"- {c['criterion']}" for c in semantic)
            + "\n\nПРОГРАММНЫЕ ГЕЙТЫ:\n"
            + (
                "\n".join(f"- {g.cmd}: {'зелёный' if g.passed else 'ГЕЙТ ПРОВАЛЕН'}" for g in gates)
                or "- нет"
            )
            + f"\n\nЧТО СДЕЛАНО:\n{evidence}\n\n"
            f"{SCHEMA_MARKER} verdict\n"
            'Верни JSON: {"verdict": "accept|reject|needs_human", "reasons": [], '
            '"next_actions": [], "criteria": []}'
        )
        try:
            completion = route.provider.complete(
                model=route.spec.id,
                messages=[Message.user(prompt)],
                system=role.system,
                max_tokens=min(role.max_output_tokens, route.spec.max_output),
            )
        except (QuotaExhausted, ProviderUnavailable) as exc:
            return Verdict(verdict="needs_human", reasons=[f"критик не отработал: {exc}"])
        self.rt.ledger.record(
            provider=route.spec.provider,
            model=route.spec.id,
            tokens_in=completion.usage.tokens_in,
            tokens_out=completion.usage.tokens_out,
            mission_id=mission_id,
            kind="critic",
        )
        return Verdict.parse(completion.json(), completion.text)

    def _collect_evidence(self, mission_id: str, max_tokens: int = 4000) -> str:
        """Собрать доказательную базу: результаты задач и список артефактов."""
        rows = self.rt.store.query(
            "SELECT title, result FROM tasks WHERE mission_id=? AND status='DONE'"
            " ORDER BY finished_at",
            (mission_id,),
        )
        lines = [f"### {r['title']}\n{(r['result'] or '').strip()}" for r in rows]
        artifacts = self.rt.artifacts.of_mission(mission_id)
        if artifacts:
            lines.append("### Артефакты\n" + "\n".join(a.as_line() for a in artifacts))
        return truncate_to_tokens("\n\n".join(lines) or "(нет выполненных задач)", max_tokens)

    def _record_semantic_criteria(self, mission_id: str, verdict: Verdict) -> None:
        """Проставить статусы семантических критериев по вердикту."""
        status = {"accept": "pass", "reject": "fail"}.get(verdict.verdict, "pending")
        with self.rt.store.tx() as conn:
            conn.execute(
                "UPDATE dod SET status=?, updated_at=? WHERE mission_id=?"
                " AND kind != 'programmatic'",
                (status, time.time(), mission_id),
            )

    def _spawn_fixes(self, mission_id: str, verdict: Verdict) -> list[str]:
        """Завести задачи на исправление вместо эскалации человеку.

        Раунды ограничены: если система не смогла починить результат за
        MAX_FIX_ROUNDS попыток, дальше решает человек.
        """
        rounds = int(
            self.rt.store.scalar(
                "SELECT COUNT(*) AS n FROM tasks WHERE mission_id=? AND title LIKE 'Исправление:%'",
                (mission_id,),
                0,
            )
        )
        if rounds >= MAX_FIX_ROUNDS * max(1, len(verdict.next_actions)):
            return []

        created: list[str] = []
        for index, action in enumerate(verdict.next_actions[:5]):
            task_id = self.rt.sm.add_task(
                mission_id,
                title=f"Исправление: {action}"[:200],
                role="coder",
                tier="large",
                priority=0,
                brief={
                    "instructions": action,
                    "constraints": ["минимальная правка, решающая ровно эту претензию"],
                },
                est_tokens=6000,
                idempotency_key=f"{mission_id}:fix:{rounds}:{index}",
            )
            created.append(task_id)
        return created
