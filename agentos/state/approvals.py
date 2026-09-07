"""Очередь подтверждений человека.

Когда агент упирается в необратимое действие, он не встаёт целиком: задача
уходит в BLOCKED_APPROVAL, остальные ветки DAG продолжают идти, а сюда
ложится запрос. Здесь он живёт до решения человека — иначе список того,
что от него требуется, существовал бы только в статусах задач и терялся из
виду между сессиями.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from ..memory.store import Store

STATUS_PENDING = "pending"
STATUS_GRANTED = "granted"
STATUS_DENIED = "denied"


@dataclass
class Approval:
    id: str
    action: str
    detail: str
    status: str
    mission_id: str = ""
    task_id: str = ""
    created_at: float = 0.0

    def as_line(self) -> str:
        task = f" (задача {self.task_id})" if self.task_id else ""
        return f"- {self.id}  {self.action}{task}: {self.detail}"


class ApprovalQueue:
    def __init__(self, store: Store) -> None:
        self.store = store

    def request(
        self, action: str, detail: str = "", *, mission_id: str = "", task_id: str = ""
    ) -> str:
        """Записать запрос. Повторный запрос по той же задаче не дублируется."""
        existing = self.store.one(
            "SELECT id FROM approvals WHERE status=? AND action=? AND task_id=?",
            (STATUS_PENDING, action, task_id),
        )
        if existing:
            return existing["id"]
        approval_id = f"ap_{uuid.uuid4().hex[:10]}"
        with self.store.tx() as conn:
            conn.execute(
                "INSERT INTO approvals(id, mission_id, task_id, action, detail, status,"
                " created_at) VALUES(?,?,?,?,?,?,?)",
                (
                    approval_id,
                    mission_id,
                    task_id,
                    action,
                    detail[:2000],
                    STATUS_PENDING,
                    time.time(),
                ),
            )
        return approval_id

    def get(self, approval_id: str) -> Approval | None:
        row = self.store.one("SELECT * FROM approvals WHERE id=?", (approval_id,))
        return self._to_approval(row) if row else None

    def pending(self, mission_id: str = "") -> list[Approval]:
        rows = self.store.query(
            "SELECT * FROM approvals WHERE status=? AND (?='' OR mission_id=?)"
            " ORDER BY created_at",
            (STATUS_PENDING, mission_id, mission_id),
        )
        return [self._to_approval(r) for r in rows]

    def decide(self, approval_id: str, *, granted: bool) -> Approval | None:
        with self.store.tx() as conn:
            conn.execute(
                "UPDATE approvals SET status=?, decided_at=? WHERE id=? AND status=?",
                (
                    STATUS_GRANTED if granted else STATUS_DENIED,
                    time.time(),
                    approval_id,
                    STATUS_PENDING,
                ),
            )
        return self.get(approval_id)

    @staticmethod
    def _to_approval(row: dict[str, Any]) -> Approval:
        return Approval(
            id=row["id"],
            action=row["action"],
            detail=row["detail"],
            status=row["status"],
            mission_id=row["mission_id"],
            task_id=row["task_id"],
            created_at=float(row["created_at"]),
        )
