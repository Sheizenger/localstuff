"""Журнал событий — эпизодическая память системы.

Два адресата на каждое событие:
  * таблица `events` — по ней строятся сводки, resume и разбор провалов;
  * файл var/events/YYYY-MM-DD.jsonl — человекочитаемый append-only лог,
    переживающий даже потерю базы.

Секреты вырезаются до записи, в обоих адресатах.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .memory.store import Store
from .policy.redact import Redactor

# Виды событий. Держим списком, чтобы сводки и тесты не разъезжались со строками.
EV_MISSION_CREATED = "mission.created"
EV_MISSION_STATUS = "mission.status"
EV_PLAN_BUILT = "plan.built"
EV_TASK_CREATED = "task.created"
EV_TASK_STARTED = "task.started"
EV_TASK_FINISHED = "task.finished"
EV_TASK_BLOCKED = "task.blocked"
EV_TASK_FAILED = "task.failed"
EV_PROVIDER_CALL = "provider.call"
EV_PROVIDER_ERROR = "provider.error"
EV_QUOTA_HIT = "quota.hit"
EV_QUOTA_CLEARED = "quota.cleared"
EV_TOOL_CALL = "tool.call"
EV_CAPABILITY_REQUEST = "capability.request"
EV_APPROVAL_REQUEST = "approval.request"
EV_CRITIC_VERDICT = "critic.verdict"
EV_GATE_RESULT = "gate.result"
EV_MEMORY_WRITE = "memory.write"
EV_SKILL_PROPOSED = "skill.proposed"
EV_RESUME = "run.resume"
EV_CHECKPOINT = "run.checkpoint"


class EventBus:
    """Пишет события. Никогда не бросает исключение наружу при записи в файл —
    потеря лога не должна ронять работу, потеря транзакции в БД — должна."""

    def __init__(
        self,
        store: Store,
        events_dir: Path | None = None,
        redactor: Redactor | None = None,
    ) -> None:
        self.store = store
        self.events_dir = events_dir
        self.redactor = redactor or Redactor()
        if self.events_dir:
            self.events_dir.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        kind: str,
        *,
        mission_id: str = "",
        task_id: str = "",
        actor: str = "",
        **payload: Any,
    ) -> int:
        """Записать событие. Возвращает его id в таблице events."""
        # 'kind', 'mission_id', 'task_id', 'actor' — имена параметров emit;
        # в payload они дают невнятный TypeError, поэтому переименовываются.
        for reserved in ("kind", "mission_id", "task_id", "actor"):
            if reserved in payload:
                payload[f"payload_{reserved}"] = payload.pop(reserved)
        ts = time.time()
        clean = self.redactor.apply(payload)
        blob = json.dumps(clean, ensure_ascii=False, default=str)
        cur = self.store.execute(
            "INSERT INTO events(ts, mission_id, task_id, actor, kind, payload)"
            " VALUES(?,?,?,?,?,?)",
            (ts, mission_id, task_id, actor, kind, blob),
        )
        event_id = int(cur.lastrowid or 0)
        self._append_file(
            {
                "id": event_id,
                "ts": ts,
                "iso": datetime.fromtimestamp(ts, UTC).isoformat(),
                "mission_id": mission_id,
                "task_id": task_id,
                "actor": actor,
                "kind": kind,
                "payload": clean,
            }
        )
        return event_id

    def _append_file(self, record: dict[str, Any]) -> None:
        if not self.events_dir:
            return
        day = datetime.fromtimestamp(record["ts"], UTC).strftime("%Y-%m-%d")
        path = self.events_dir / f"{day}.jsonl"
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError:
            # Журнал в файле — удобство, а не источник правды. БД уже записана.
            pass

    # ------------------------------------------------------------------ read
    def tail(self, mission_id: str = "", limit: int = 50) -> list[dict[str, Any]]:
        if mission_id:
            rows = self.store.query(
                "SELECT * FROM events WHERE mission_id=? ORDER BY id DESC LIMIT ?",
                (mission_id, limit),
            )
        else:
            rows = self.store.query("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
        for row in rows:
            row["payload"] = json.loads(row["payload"] or "{}")
        return list(reversed(rows))

    def of_kind(self, kind: str, mission_id: str = "", limit: int = 200) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT * FROM events WHERE kind=? AND (?='' OR mission_id=?)"
            " ORDER BY id DESC LIMIT ?",
            (kind, mission_id, mission_id, limit),
        )
        for row in rows:
            row["payload"] = json.loads(row["payload"] or "{}")
        return list(reversed(rows))
