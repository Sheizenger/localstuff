"""Машина состояний миссий и задач.

Всё, что делает система, проходит через эти переходы. Каждый переход —
транзакция в SQLite, поэтому падение процесса в любой момент оставляет
согласованное состояние, с которого resume продолжит без дублей.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..errors import InvalidTransition
from ..memory.store import Store


class TaskStatus(str, Enum):
    PENDING = "PENDING"                        # создана, зависимости не готовы
    READY = "READY"                            # можно брать в работу
    RUNNING = "RUNNING"                        # взята исполнителем
    DONE = "DONE"                              # результат принят
    FAILED = "FAILED"                          # исчерпаны попытки
    BLOCKED_QUOTA = "BLOCKED_QUOTA"            # ждёт сброса лимитов
    BLOCKED_APPROVAL = "BLOCKED_APPROVAL"      # ждёт человека
    BLOCKED_CAPABILITY = "BLOCKED_CAPABILITY"  # не хватает доступа/секрета
    CANCELLED = "CANCELLED"


class MissionStatus(str, Enum):
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"      # результат собран, работает критик и гейты
    BLOCKED = "BLOCKED"          # всё, что можно, сделано; ждём внешнего
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


#: Разрешённые переходы задач. Всё остальное — баг, а не внешний сбой.
TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.READY: frozenset(
        {TaskStatus.RUNNING, TaskStatus.PENDING, TaskStatus.CANCELLED}
    ),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.DONE,
            TaskStatus.FAILED,
            TaskStatus.READY,  # повтор после устранимой ошибки
            TaskStatus.BLOCKED_QUOTA,
            TaskStatus.BLOCKED_APPROVAL,
            TaskStatus.BLOCKED_CAPABILITY,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.BLOCKED_QUOTA: frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.BLOCKED_APPROVAL: frozenset(
        {TaskStatus.READY, TaskStatus.CANCELLED, TaskStatus.FAILED}
    ),
    TaskStatus.BLOCKED_CAPABILITY: frozenset(
        {TaskStatus.READY, TaskStatus.CANCELLED, TaskStatus.FAILED}
    ),
    # Терминальные: FAILED можно перезапустить руками, DONE — нет.
    TaskStatus.FAILED: frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.DONE: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

#: Статусы, из которых работа ещё может продолжиться сама.
RESUMABLE = frozenset(
    {
        TaskStatus.PENDING,
        TaskStatus.READY,
        TaskStatus.RUNNING,
        TaskStatus.BLOCKED_QUOTA,
    }
)

#: Статусы, требующие человека.
NEEDS_HUMAN = frozenset({TaskStatus.BLOCKED_APPROVAL, TaskStatus.BLOCKED_CAPABILITY})


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class Task:
    """Узел DAG. Поля повторяют колонки таблицы tasks."""

    id: str
    mission_id: str
    title: str
    role: str
    tier: str
    status: TaskStatus
    priority: int = 2
    parent_id: str | None = None
    brief: dict[str, Any] | None = None
    result: str = ""
    attempts: int = 0
    est_tokens: int = 0
    used_tokens: int = 0
    used_usd: float = 0.0
    budget_tokens: int = 0
    idempotency_key: str | None = None
    blocked_reason: str = ""
    resume_after: float | None = None
    provider: str = ""
    model: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Task:
        return cls(
            id=row["id"],
            mission_id=row["mission_id"],
            title=row["title"],
            role=row["role"],
            tier=row["tier"],
            status=TaskStatus(row["status"]),
            priority=int(row["priority"]),
            parent_id=row["parent_id"],
            brief=json.loads(row["brief"] or "{}"),
            result=row["result"],
            attempts=int(row["attempts"]),
            est_tokens=int(row["est_tokens"]),
            used_tokens=int(row["used_tokens"]),
            used_usd=float(row["used_usd"]),
            budget_tokens=int(row["budget_tokens"]),
            idempotency_key=row["idempotency_key"],
            blocked_reason=row["blocked_reason"],
            resume_after=row["resume_after"],
            provider=row["provider"],
            model=row["model"],
        )


class StateMachine:
    """Все операции над состоянием. Единственный, кто пишет в missions/tasks."""

    def __init__(self, store: Store) -> None:
        self.store = store

    # ------------------------------------------------------------- missions
    def create_mission(
        self,
        goal: str,
        *,
        context: str = "",
        budget_tokens: int = 0,
        budget_usd: float = 0.0,
        mode: str = "auto",
        meta: dict[str, Any] | None = None,
    ) -> str:
        mission_id = new_id("m")
        now = time.time()
        with self.store.tx() as conn:
            conn.execute(
                "INSERT INTO missions(id, goal, context, status, mode, budget_tokens,"
                " budget_usd, meta, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    mission_id,
                    goal,
                    context,
                    MissionStatus.PLANNING.value,
                    mode,
                    budget_tokens,
                    budget_usd,
                    json.dumps(meta or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return mission_id

    def get_mission(self, mission_id: str) -> dict[str, Any] | None:
        return self.store.one("SELECT * FROM missions WHERE id=?", (mission_id,))

    def set_mission_status(
        self,
        mission_id: str,
        status: MissionStatus,
        *,
        blocked_reason: str = "",
        resume_after: float | None = None,
    ) -> None:
        with self.store.tx() as conn:
            conn.execute(
                "UPDATE missions SET status=?, blocked_reason=?, resume_after=?, updated_at=?"
                " WHERE id=?",
                (status.value, blocked_reason, resume_after, time.time(), mission_id),
            )

    def active_missions(self) -> list[dict[str, Any]]:
        """Миссии, которые ещё не закончены."""
        return self.store.query(
            "SELECT * FROM missions WHERE status NOT IN (?,?,?) ORDER BY created_at",
            (MissionStatus.DONE.value, MissionStatus.FAILED.value, MissionStatus.CANCELLED.value),
        )

    # ---------------------------------------------------------------- tasks
    def add_task(
        self,
        mission_id: str,
        *,
        title: str,
        role: str,
        tier: str = "small",
        priority: int = 2,
        brief: dict[str, Any] | None = None,
        depends_on: list[str] | None = None,
        est_tokens: int = 0,
        budget_tokens: int = 0,
        idempotency_key: str | None = None,
        parent_id: str | None = None,
    ) -> str:
        """Добавить задачу. При совпадении idempotency_key вернёт существующую.

        Именно это делает resume безопасным: повторное планирование не
        плодит дубликаты уже выполненной работы.
        """
        if idempotency_key:
            existing = self.store.one(
                "SELECT id FROM tasks WHERE idempotency_key=?", (idempotency_key,)
            )
            if existing:
                return existing["id"]

        task_id = new_id("t")
        now = time.time()
        deps = depends_on or []
        status = TaskStatus.PENDING if deps else TaskStatus.READY
        with self.store.tx() as conn:
            conn.execute(
                "INSERT INTO tasks(id, mission_id, parent_id, title, role, tier, priority,"
                " status, brief, est_tokens, budget_tokens, idempotency_key,"
                " created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    mission_id,
                    parent_id,
                    title,
                    role,
                    tier,
                    priority,
                    status.value,
                    json.dumps(brief or {}, ensure_ascii=False),
                    est_tokens,
                    budget_tokens,
                    idempotency_key,
                    now,
                    now,
                ),
            )
            for dep in deps:
                conn.execute(
                    "INSERT OR IGNORE INTO task_deps(task_id, depends_on) VALUES(?,?)",
                    (task_id, dep),
                )
        return task_id

    def get_task(self, task_id: str) -> Task | None:
        row = self.store.one("SELECT * FROM tasks WHERE id=?", (task_id,))
        return Task.from_row(row) if row else None

    def tasks_of(self, mission_id: str) -> list[Task]:
        rows = self.store.query(
            "SELECT * FROM tasks WHERE mission_id=? ORDER BY priority, created_at",
            (mission_id,),
        )
        return [Task.from_row(r) for r in rows]

    def _assert_transition(self, current: TaskStatus, target: TaskStatus) -> None:
        if target not in TASK_TRANSITIONS[current]:
            raise InvalidTransition(f"недопустимый переход задачи: {current.value} -> {target.value}")

    def transition(
        self,
        task_id: str,
        target: TaskStatus,
        *,
        result: str | None = None,
        blocked_reason: str = "",
        resume_after: float | None = None,
        provider: str = "",
        model: str = "",
        bump_attempt: bool = False,
    ) -> None:
        """Перевести задачу в новый статус с проверкой допустимости."""
        with self.store.tx() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise InvalidTransition(f"нет такой задачи: {task_id}")
            current = TaskStatus(row["status"])
            if current == target:
                return
            self._assert_transition(current, target)

            now = time.time()
            started = row["started_at"] or (now if target is TaskStatus.RUNNING else None)
            finished = (
                now
                if target in {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED}
                else None
            )
            conn.execute(
                "UPDATE tasks SET status=?, result=COALESCE(?, result), blocked_reason=?,"
                " resume_after=?, provider=COALESCE(NULLIF(?,''), provider),"
                " model=COALESCE(NULLIF(?,''), model), attempts=attempts+?,"
                " started_at=?, finished_at=?, updated_at=? WHERE id=?",
                (
                    target.value,
                    result,
                    blocked_reason,
                    resume_after,
                    provider,
                    model,
                    1 if bump_attempt else 0,
                    started,
                    finished,
                    now,
                    task_id,
                ),
            )
            if target is TaskStatus.DONE:
                self._promote_dependents(conn, task_id)

    @staticmethod
    def _promote_dependents(conn: Any, done_task_id: str) -> None:
        """Перевести PENDING-задачи в READY, если все их зависимости выполнены."""
        dependents = conn.execute(
            "SELECT task_id FROM task_deps WHERE depends_on=?", (done_task_id,)
        ).fetchall()
        for dep in dependents:
            tid = dep["task_id"]
            blocking = conn.execute(
                "SELECT COUNT(*) AS n FROM task_deps d JOIN tasks t ON t.id = d.depends_on"
                " WHERE d.task_id=? AND t.status != ?",
                (tid, TaskStatus.DONE.value),
            ).fetchone()["n"]
            if blocking == 0:
                conn.execute(
                    "UPDATE tasks SET status=?, updated_at=? WHERE id=? AND status=?",
                    (TaskStatus.READY.value, time.time(), tid, TaskStatus.PENDING.value),
                )

    def claim_next(
        self, mission_id: str, *, roles: list[str] | None = None
    ) -> Task | None:
        """Атомарно взять следующую READY-задачу (приоритет, затем возраст).

        Атомарность важна: несколько исполнителей могут работать параллельно,
        и одну задачу не должны взять двое.
        """
        with self.store.tx() as conn:
            sql = (
                "SELECT * FROM tasks WHERE mission_id=? AND status=?"
                + (
                    " AND role IN (%s)" % ",".join("?" * len(roles))
                    if roles
                    else ""
                )
                + " ORDER BY priority, created_at LIMIT 1"
            )
            params: list[Any] = [mission_id, TaskStatus.READY.value, *(roles or [])]
            row = conn.execute(sql, tuple(params)).fetchone()
            if not row:
                return None
            now = time.time()
            conn.execute(
                "UPDATE tasks SET status=?, started_at=COALESCE(started_at, ?),"
                " attempts=attempts+1, updated_at=? WHERE id=?",
                (TaskStatus.RUNNING.value, now, now, row["id"]),
            )
            row["status"] = TaskStatus.RUNNING.value
            row["attempts"] = int(row["attempts"]) + 1
            return Task.from_row(row)

    def release_stale_running(self, older_than_s: float) -> int:
        """Вернуть в READY задачи, зависшие в RUNNING (процесс убит).

        Так падение сессии не оставляет вечно «выполняющихся» задач.
        """
        cutoff = time.time() - older_than_s
        with self.store.tx() as conn:
            cur = conn.execute(
                "UPDATE tasks SET status=?, updated_at=?, blocked_reason=?"
                " WHERE status=? AND COALESCE(updated_at, 0) < ?",
                (
                    TaskStatus.READY.value,
                    time.time(),
                    "процесс-исполнитель пропал, задача возвращена в очередь",
                    TaskStatus.RUNNING.value,
                    cutoff,
                ),
            )
            return cur.rowcount

    def unblock_due(self, now: float | None = None) -> int:
        """Разблокировать задачи, у которых истёк срок ожидания квоты."""
        moment = now if now is not None else time.time()
        with self.store.tx() as conn:
            cur = conn.execute(
                "UPDATE tasks SET status=?, blocked_reason='', resume_after=NULL, updated_at=?"
                " WHERE status=? AND resume_after IS NOT NULL AND resume_after <= ?",
                (TaskStatus.READY.value, moment, TaskStatus.BLOCKED_QUOTA.value, moment),
            )
            return cur.rowcount

    # ------------------------------------------------------------- summaries
    def status_counts(self, mission_id: str) -> dict[str, int]:
        rows = self.store.query(
            "SELECT status, COUNT(*) AS n FROM tasks WHERE mission_id=? GROUP BY status",
            (mission_id,),
        )
        return {r["status"]: int(r["n"]) for r in rows}

    def next_resume_at(self, mission_id: str | None = None) -> float | None:
        """Ближайший момент, когда что-то само сдвинется с места."""
        sql = (
            "SELECT MIN(resume_after) AS t FROM tasks WHERE status=? AND resume_after IS NOT NULL"
        )
        params: list[Any] = [TaskStatus.BLOCKED_QUOTA.value]
        if mission_id:
            sql += " AND mission_id=?"
            params.append(mission_id)
        value = self.store.scalar(sql, tuple(params))
        return float(value) if value is not None else None

    def is_mission_settled(self, mission_id: str) -> bool:
        """Не осталось ли задач, которые система может двигать сама."""
        counts = self.status_counts(mission_id)
        return not any(counts.get(s.value, 0) for s in RESUMABLE)
