"""Планирование: миссия -> DAG задач.

План строит модель тира reasoning, но результат всегда валидируется кодом:
неизвестная роль заменяется подбором по триггерам, циклы в зависимостях
разрываются, оценки токенов урезаются под бюджет. Модель предлагает —
система отвечает за то, что план исполним.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..agents.roles import RoleRouter
from ..bus import EV_PLAN_BUILT, EV_TASK_CREATED
from ..errors import ProviderUnavailable, QuotaExhausted
from ..memory.working import GOAL_MARKER, SCHEMA_MARKER
from ..providers.base import Message
from ..runtime import Runtime

PLANNER_SYSTEM_SUFFIX = """
Верни JSON: {"tasks": [{key, title, role, tier, priority, est_tokens, depends_on[], instructions}]}
Требования:
- key — короткий латинский идентификатор, уникальный внутри плана;
- depends_on ссылается только на key из этого же плана;
- независимые задачи НЕ связывай зависимостями: они пойдут параллельно;
- tier: nano | small | large | reasoning — по сложности, а не «на всякий случай»;
- priority: 0 (критично) … 3 (можно отложить).
"""

#: Запасной план, когда модель недоступна: минимальный исполнимый скелет.
FALLBACK_PLAN: list[dict[str, Any]] = [
    {
        "key": "explore",
        "title": "Разобраться в задаче и собрать вводные",
        "role": "researcher",
        "tier": "small",
        "priority": 1,
        "est_tokens": 4000,
        "depends_on": [],
        "instructions": "Собери всё необходимое для выполнения цели.",
    },
    {
        "key": "build",
        "title": "Выполнить основную работу",
        "role": "coder",
        "tier": "large",
        "priority": 1,
        "est_tokens": 12000,
        "depends_on": ["explore"],
        "instructions": "Сделай результат, отвечающий критериям приёмки.",
    },
    {
        "key": "verify",
        "title": "Проверить результат и прогнать гейты",
        "role": "reviewer",
        "tier": "large",
        "priority": 0,
        "est_tokens": 4000,
        "depends_on": ["build"],
        "instructions": "Проверь результат против критериев приёмки.",
    },
]


@dataclass
class PlannedTask:
    key: str
    title: str
    role: str
    tier: str
    priority: int = 2
    est_tokens: int = 4000
    depends_on: list[str] = field(default_factory=list)
    instructions: str = ""


class Planner:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime
        self.roles = RoleRouter(runtime.config)

    # ---------------------------------------------------------------- построение
    def build(self, mission_id: str) -> list[PlannedTask]:
        mission = self.rt.sm.get_mission(mission_id) or {}
        goal = mission.get("goal", "")
        criteria = self.rt.store.query(
            "SELECT criterion FROM dod WHERE mission_id=? ORDER BY ord", (mission_id,)
        )
        raw = self._ask_model(goal, [c["criterion"] for c in criteria])
        return self._validate(raw, goal)

    def _ask_model(self, goal: str, criteria: list[str]) -> list[dict[str, Any]]:
        route = self.rt.router.try_pick("reasoning")
        if route is None:
            return FALLBACK_PLAN
        role = self.rt.config.role("planner")
        prompt = (
            f"{GOAL_MARKER} {goal}\n\n"
            "КРИТЕРИИ ПРИЁМКИ:\n" + "\n".join(f"- {c}" for c in criteria) + "\n\n"
            "ДОСТУПНЫЕ РОЛИ:\n" + "\n".join(self.roles.catalog_lines()) + "\n\n"
            f"{SCHEMA_MARKER} task_dag"
        )
        try:
            completion = route.provider.complete(
                model=route.spec.id,
                messages=[Message.user(prompt)],
                system=role.system + PLANNER_SYSTEM_SUFFIX,
                max_tokens=min(role.max_output_tokens, route.spec.max_output),
            )
        except (QuotaExhausted, ProviderUnavailable):
            return FALLBACK_PLAN
        self.rt.ledger.record(
            provider=route.spec.provider,
            model=route.spec.id,
            tokens_in=completion.usage.tokens_in,
            tokens_out=completion.usage.tokens_out,
            kind="planning",
        )
        payload = completion.json()
        tasks = payload.get("tasks") if isinstance(payload, dict) else None
        return tasks if isinstance(tasks, list) and tasks else FALLBACK_PLAN

    # ---------------------------------------------------------------- валидация
    def _validate(self, raw: list[dict[str, Any]], goal: str) -> list[PlannedTask]:
        """Привести план модели к исполнимому виду."""
        tasks: list[PlannedTask] = []
        seen: set[str] = set()
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or f"Шаг {index + 1}").strip()
            key = str(item.get("key") or f"t{index}").strip()
            if key in seen:
                key = f"{key}_{index}"
            seen.add(key)
            role_spec = self.roles.pick(f"{title} {item.get('instructions', '')}",
                                        hint=str(item.get("role", "")))
            tier = str(item.get("tier") or role_spec.tier)
            if tier not in {"nano", "small", "large", "reasoning"}:
                tier = role_spec.tier
            tasks.append(
                PlannedTask(
                    key=key,
                    title=title,
                    role=role_spec.name,
                    tier=tier,
                    priority=_clamp_priority(item.get("priority", role_spec.priority_rank)),
                    est_tokens=max(500, min(int(item.get("est_tokens", 4000) or 4000), 200000)),
                    depends_on=[str(d) for d in item.get("depends_on", []) or []],
                    instructions=str(item.get("instructions", "")).strip(),
                )
            )
        if not tasks:
            return self._validate(FALLBACK_PLAN, goal)
        return _drop_cycles(_drop_unknown_deps(tasks))

    # ----------------------------------------------------------------- запись
    def persist(self, mission_id: str, tasks: list[PlannedTask]) -> dict[str, str]:
        """Записать план в БД. Идемпотентно по (миссия, ключ задачи)."""
        spend = self.rt.ledger.mission_spend(mission_id)
        total_est = sum(t.est_tokens for t in tasks) or 1
        reserve = float(self.rt.config.get("budget.reserve_fraction", 0.25))
        spendable = int(spend.tokens_left * (1.0 - reserve)) if spend.budget_tokens else 0

        key_to_id: dict[str, str] = {}
        for task in tasks:
            # Доля бюджета пропорциональна оценке — так дорогие задачи не
            # выедают весь бюджет до того, как дойдёт очередь до остальных.
            budget = int(spendable * task.est_tokens / total_est) if spendable else 0
            task_id = self.rt.sm.add_task(
                mission_id,
                title=task.title,
                role=task.role,
                tier=task.tier,
                priority=task.priority,
                brief={"instructions": task.instructions, "plan_key": task.key},
                depends_on=[key_to_id[d] for d in task.depends_on if d in key_to_id],
                est_tokens=task.est_tokens,
                budget_tokens=budget,
                idempotency_key=f"{mission_id}:{task.key}",
            )
            key_to_id[task.key] = task_id
            self.rt.bus.emit(
                EV_TASK_CREATED,
                mission_id=mission_id,
                task_id=task_id,
                title=task.title,
                role=task.role,
                tier=task.tier,
                est_tokens=task.est_tokens,
                budget_tokens=budget,
            )
        self.rt.bus.emit(
            EV_PLAN_BUILT,
            mission_id=mission_id,
            tasks=len(tasks),
            parallel_roots=sum(1 for t in tasks if not t.depends_on),
        )
        return key_to_id


def _clamp_priority(value: Any) -> int:
    try:
        return max(0, min(3, int(value)))
    except (TypeError, ValueError):
        return 2


def _drop_unknown_deps(tasks: list[PlannedTask]) -> list[PlannedTask]:
    known = {t.key for t in tasks}
    for task in tasks:
        task.depends_on = [d for d in task.depends_on if d in known and d != task.key]
    return tasks


def _drop_cycles(tasks: list[PlannedTask]) -> list[PlannedTask]:
    """Разорвать циклы: план с циклом не исполним вообще, лучше потерять связь."""
    by_key = {t.key: t for t in tasks}
    state: dict[str, int] = {}

    def visit(key: str) -> None:
        state[key] = 1
        for dep in list(by_key[key].depends_on):
            if state.get(dep) == 1:
                by_key[key].depends_on.remove(dep)
            elif state.get(dep, 0) == 0 and dep in by_key:
                visit(dep)
        state[key] = 2

    for task in tasks:
        if state.get(task.key, 0) == 0:
            visit(task.key)
    return tasks
