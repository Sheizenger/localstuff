"""Эпизодическая память: что происходило в прогоне.

Главное здесь — не хранение (это делает bus), а *сжатие*. Новой сессии
нельзя отдать весь журнал: он не влезет в контекст и не нужен целиком.
Отдаётся дайджест: решения, результаты задач, блокировки, провалы.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..bus import (
    EV_APPROVAL_REQUEST,
    EV_CAPABILITY_REQUEST,
    EV_CRITIC_VERDICT,
    EV_GATE_RESULT,
    EV_QUOTA_HIT,
    EV_TASK_BLOCKED,
    EV_TASK_FAILED,
    EV_TASK_FINISHED,
)
from .store import Store

#: События, которые входят в дайджест. Остальное — шум для следующей сессии.
DIGEST_KINDS = (
    EV_TASK_FINISHED,
    EV_TASK_FAILED,
    EV_TASK_BLOCKED,
    EV_CRITIC_VERDICT,
    EV_GATE_RESULT,
    EV_QUOTA_HIT,
    EV_CAPABILITY_REQUEST,
    EV_APPROVAL_REQUEST,
)


@dataclass
class Episode:
    ts: float
    kind: str
    task_id: str
    actor: str
    payload: dict[str, Any]

    def as_line(self) -> str:
        stamp = datetime.fromtimestamp(self.ts, UTC).strftime("%H:%M:%S")
        summary = (
            self.payload.get("summary")
            or self.payload.get("reason")
            or self.payload.get("verdict")
            or self.payload.get("title")
            or ""
        )
        text = str(summary).strip().replace("\n", " ")
        if len(text) > 220:
            text = text[:217] + "..."
        who = f" [{self.actor}]" if self.actor else ""
        return f"{stamp} {self.kind}{who}: {text}"


class EpisodicMemory:
    def __init__(self, store: Store) -> None:
        self.store = store

    def episodes(
        self, mission_id: str, *, kinds: tuple[str, ...] = DIGEST_KINDS, limit: int = 200
    ) -> list[Episode]:
        placeholders = ",".join("?" * len(kinds)) if kinds else ""
        sql = "SELECT ts, kind, task_id, actor, payload FROM events WHERE mission_id=?"
        params: list[Any] = [mission_id]
        if kinds:
            sql += f" AND kind IN ({placeholders})"
            params += list(kinds)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self.store.query(sql, tuple(params))
        out = [
            Episode(
                ts=float(r["ts"]),
                kind=r["kind"],
                task_id=r["task_id"],
                actor=r["actor"],
                payload=json.loads(r["payload"] or "{}"),
            )
            for r in rows
        ]
        return list(reversed(out))

    def digest(self, mission_id: str, *, max_lines: int = 40) -> str:
        """Сжатый ход работы — то, что вставляется в контекст при resume."""
        episodes = self.episodes(mission_id)
        if not episodes:
            return "(событий пока нет)"
        lines = [e.as_line() for e in episodes]
        if len(lines) > max_lines:
            head = lines[: max_lines // 2]
            tail = lines[-(max_lines - len(head)) :]
            skipped = len(lines) - len(head) - len(tail)
            lines = [*head, f"... пропущено событий: {skipped} ...", *tail]
        return "\n".join(lines)

    def task_results(self, mission_id: str) -> dict[str, str]:
        """Итоги выполненных задач: id задачи -> краткий результат."""
        rows = self.store.query(
            "SELECT id, title, result FROM tasks WHERE mission_id=? AND status='DONE'"
            " ORDER BY finished_at",
            (mission_id,),
        )
        return {r["id"]: (r["result"] or "").strip() for r in rows}

    def failures(self, mission_id: str, limit: int = 20) -> list[Episode]:
        return self.episodes(
            mission_id, kinds=(EV_TASK_FAILED, EV_GATE_RESULT), limit=limit
        )

    def counts(self, mission_id: str) -> dict[str, int]:
        rows = self.store.query(
            "SELECT kind, COUNT(*) AS n FROM events WHERE mission_id=? GROUP BY kind",
            (mission_id,),
        )
        return {r["kind"]: int(r["n"]) for r in rows}
