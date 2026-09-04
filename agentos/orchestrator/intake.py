"""Приём цели: абстрактная формулировка -> миссия с критериями приёмки.

Ключевая идея: критерии приёмки (DoD) фиксируются ДО работы. Иначе
«готово» определяется постфактум тем же агентом, который делал работу, —
и проверка превращается в самоподтверждение.

Программные гейты (тесты, линт) добавляются из конфига всегда: критик
не может их переспорить, красный гейт — это отказ.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..bus import EV_MISSION_CREATED
from ..errors import ProviderUnavailable, QuotaExhausted
from ..memory.working import GOAL_MARKER, SCHEMA_MARKER
from ..providers.base import Message
from ..runtime import Runtime

INTAKE_SYSTEM = """Ты принимаешь задачу от человека, который формулирует её высокоуровнево.

Твоя работа — превратить формулировку в проверяемую постановку:
- переформулируй цель одним предложением, без воды;
- выпиши допущения, которые ты делаешь вместо уточняющих вопросов;
- задавай вопрос ТОЛЬКО если без ответа работа пойдёт в заведомо неверную
  сторону. Максимум два вопроса;
- сформулируй критерии приёмки: по ним потом судит критик. Критерий должен
  быть проверяемым: «работает» — не критерий, «make test зелёный» — критерий.
"""


@dataclass
class MissionSpec:
    goal: str
    assumptions: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    acceptance: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def parse(cls, payload: Any, fallback_goal: str) -> MissionSpec:
        if not isinstance(payload, dict):
            return cls(goal=fallback_goal)
        criteria = []
        for item in payload.get("acceptance_criteria", []) or []:
            if isinstance(item, str):
                criteria.append({"criterion": item, "kind": "semantic", "cmd": ""})
            elif isinstance(item, dict) and item.get("criterion"):
                criteria.append(
                    {
                        "criterion": str(item["criterion"]),
                        "kind": str(item.get("kind", "semantic")),
                        "cmd": str(item.get("cmd", "")),
                    }
                )
        return cls(
            goal=str(payload.get("restated_goal") or fallback_goal),
            assumptions=[str(a) for a in payload.get("assumptions", []) or []],
            questions=[str(q) for q in payload.get("questions", []) or []][:2],
            acceptance=criteria,
        )


class Intake:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    def create(
        self,
        goal: str,
        *,
        context: str = "",
        budget_tokens: int = 0,
        budget_usd: float = 0.0,
    ) -> tuple[str, MissionSpec]:
        """Создать миссию и зафиксировать критерии приёмки."""
        mission_id = self.rt.sm.create_mission(
            goal,
            context=context,
            budget_tokens=budget_tokens or int(self.rt.config.get("budget.mission_tokens", 0)),
            budget_usd=budget_usd or float(self.rt.config.get("budget.mission_usd", 0.0)),
            mode=self.rt.mode,
        )
        spec = self._elicit(goal, context)
        self._persist_dod(mission_id, spec)
        self.rt.bus.emit(
            EV_MISSION_CREATED,
            mission_id=mission_id,
            goal=spec.goal,
            criteria=len(spec.acceptance),
            questions=spec.questions,
            mode=self.rt.mode,
        )
        self.rt.checkpointer.write(mission_id)
        return mission_id, spec

    # ------------------------------------------------------------- получение
    def _elicit(self, goal: str, context: str) -> MissionSpec:
        """Спросить модель. Без доступной модели — детерминированный минимум."""
        route = self.rt.router.try_pick("reasoning")
        if route is None:
            return self._heuristic_spec(goal)
        prompt = (
            f"{GOAL_MARKER} {goal}\n"
            + (f"КОНТЕКСТ: {context}\n" if context else "")
            + f"\n{SCHEMA_MARKER} mission_spec\n"
            "Верни JSON: restated_goal, assumptions[], questions[], "
            "acceptance_criteria[{criterion, kind: semantic|programmatic, cmd}]"
        )
        try:
            completion = route.provider.complete(
                model=route.spec.id,
                messages=[Message.user(prompt)],
                system=INTAKE_SYSTEM,
                max_tokens=min(2000, route.spec.max_output),
            )
        except (QuotaExhausted, ProviderUnavailable, Exception):
            # Приём цели не должен падать из-за провайдера: минимальный
            # набор критериев всегда лучше, чем отсутствие миссии.
            return self._heuristic_spec(goal)
        self.rt.ledger.record(
            provider=route.spec.provider,
            model=route.spec.id,
            tokens_in=completion.usage.tokens_in,
            tokens_out=completion.usage.tokens_out,
            kind="intake",
        )
        spec = MissionSpec.parse(completion.json(), goal)
        if not spec.acceptance:
            spec.acceptance = self._heuristic_spec(goal).acceptance
        return spec

    def _heuristic_spec(self, goal: str) -> MissionSpec:
        return MissionSpec(
            goal=goal,
            assumptions=["постановка уточнена не моделью, а по умолчанию"],
            acceptance=[
                {"criterion": f"результат отвечает цели: {goal}", "kind": "semantic", "cmd": ""}
            ],
        )

    # -------------------------------------------------------------- хранение
    def _persist_dod(self, mission_id: str, spec: MissionSpec) -> None:
        rows = list(spec.acceptance)
        for gate in self.rt.config.get("self_check.programmatic_gates", []) or []:
            rows.append(
                {
                    "criterion": f"программный гейт '{gate.get('name')}' зелёный",
                    "kind": "programmatic",
                    "cmd": str(gate.get("cmd", "")),
                }
            )
        now = time.time()
        with self.rt.store.tx() as conn:
            for index, row in enumerate(rows):
                conn.execute(
                    "INSERT INTO dod(id, mission_id, ord, criterion, kind, cmd, updated_at)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (
                        f"d_{uuid.uuid4().hex[:12]}",
                        mission_id,
                        index,
                        row["criterion"],
                        row.get("kind", "semantic"),
                        row.get("cmd", ""),
                        now,
                    ),
                )
            if spec.assumptions or spec.questions:
                conn.execute(
                    "UPDATE missions SET context = context || ? WHERE id=?",
                    (
                        "\nдопущения: "
                        + "; ".join(spec.assumptions)
                        + ("\nвопросы: " + "; ".join(spec.questions) if spec.questions else ""),
                        mission_id,
                    ),
                )

    def add_criterion(
        self, mission_id: str, criterion: str, *, kind: str = "semantic", cmd: str = ""
    ) -> str:
        """Добавить критерий вручную — так человек правит DoD на лету."""
        dod_id = f"d_{uuid.uuid4().hex[:12]}"
        order = int(
            self.rt.store.scalar(
                "SELECT COALESCE(MAX(ord), -1) + 1 AS n FROM dod WHERE mission_id=?",
                (mission_id,),
                0,
            )
        )
        with self.rt.store.tx() as conn:
            conn.execute(
                "INSERT INTO dod(id, mission_id, ord, criterion, kind, cmd, updated_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (dod_id, mission_id, order, criterion, kind, cmd, time.time()),
            )
        return dod_id
