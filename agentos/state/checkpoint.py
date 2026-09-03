"""Чекпоинты — то, ради чего система переживает обрыв сессии и лимиты.

БД уже содержит полное состояние, но чекпоинт решает вторую задачу:
дать *новой сессии другого агент-хоста* понять за одно чтение, что
происходит и что делать дальше, не разбирая транскрипт.

Файлы:
  var/runs/<mission_id>/state.json — снимок миссии (DAG, DoD, блокировки)
  var/resume.json                  — «что подхватить первым» для всей системы

Запись атомарная (temp + rename): недописанный чекпоинт невозможен.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from ..memory.store import Store
from .machine import NEEDS_HUMAN, MissionStatus, StateMachine, TaskStatus


def atomic_write_json(path: Path, data: Any) -> None:
    """Записать JSON так, чтобы читатель никогда не увидел половину файла."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    payload = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


class Checkpointer:
    """Снимает состояние миссии на диск после каждого значимого перехода."""

    def __init__(self, store: Store, runs_dir: Path, home: Path) -> None:
        self.store = store
        self.runs_dir = runs_dir
        self.home = home
        self.sm = StateMachine(store)

    # ------------------------------------------------------------------ paths
    def mission_dir(self, mission_id: str) -> Path:
        return self.runs_dir / mission_id

    def state_path(self, mission_id: str) -> Path:
        return self.mission_dir(mission_id) / "state.json"

    @property
    def resume_path(self) -> Path:
        return self.home / "resume.json"

    # ------------------------------------------------------------------ write
    def snapshot(self, mission_id: str) -> dict[str, Any]:
        """Собрать снимок миссии из БД."""
        mission = self.sm.get_mission(mission_id) or {}
        tasks = self.sm.tasks_of(mission_id)
        dod = self.store.query(
            "SELECT criterion, kind, cmd, status, evidence FROM dod"
            " WHERE mission_id=? ORDER BY ord",
            (mission_id,),
        )
        blocked = [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status.value,
                "reason": t.blocked_reason,
                "resume_after": t.resume_after,
            }
            for t in tasks
            if t.status in NEEDS_HUMAN or t.status is TaskStatus.BLOCKED_QUOTA
        ]
        next_up = [
            {"id": t.id, "title": t.title, "role": t.role, "tier": t.tier}
            for t in tasks
            if t.status in {TaskStatus.READY, TaskStatus.RUNNING}
        ][:5]
        return {
            "schema": 1,
            "written_at": time.time(),
            "mission": {
                "id": mission_id,
                "goal": mission.get("goal", ""),
                "status": mission.get("status", ""),
                "used_tokens": mission.get("used_tokens", 0),
                "used_usd": mission.get("used_usd", 0.0),
                "budget_tokens": mission.get("budget_tokens", 0),
                "budget_usd": mission.get("budget_usd", 0.0),
            },
            "dod": dod,
            "counts": self.sm.status_counts(mission_id),
            "next_up": next_up,
            "blocked": blocked,
            "resume_at": self.sm.next_resume_at(mission_id),
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "role": t.role,
                    "status": t.status.value,
                    "attempts": t.attempts,
                    "used_tokens": t.used_tokens,
                }
                for t in tasks
            ],
        }

    def write(self, mission_id: str) -> dict[str, Any]:
        """Записать чекпоинт миссии и обновить глобальный указатель resume."""
        snap = self.snapshot(mission_id)
        atomic_write_json(self.state_path(mission_id), snap)
        self.refresh_resume_pointer()
        return snap

    def refresh_resume_pointer(self) -> dict[str, Any]:
        """Пересобрать var/resume.json: что подхватить в следующей сессии.

        Этот файл — контракт с агент-хостом. Его читает SessionStart-хук и
        инструкция в AGENTS.md, поэтому он должен быть понятен без кода.
        """
        missions = self.sm.active_missions()
        entries = []
        for m in missions:
            counts = self.sm.status_counts(m["id"])
            entries.append(
                {
                    "mission_id": m["id"],
                    "goal": m["goal"],
                    "status": m["status"],
                    "counts": counts,
                    "resume_at": self.sm.next_resume_at(m["id"]),
                    "needs_human": sum(counts.get(s.value, 0) for s in NEEDS_HUMAN),
                    "state_file": str(self.state_path(m["id"])),
                }
            )
        pointer = {
            "schema": 1,
            "written_at": time.time(),
            "has_work": any(
                not self.sm.is_mission_settled(e["mission_id"]) for e in entries
            ),
            "missions": entries,
            "how_to_continue": "agentctl resume  (или: make resume)",
        }
        atomic_write_json(self.resume_path, pointer)
        return pointer

    # ------------------------------------------------------------------- read
    def load(self, mission_id: str) -> dict[str, Any] | None:
        return read_json(self.state_path(mission_id))

    def resume_pointer(self) -> dict[str, Any]:
        return read_json(self.resume_path, {"has_work": False, "missions": []})

    def settle_missions(self) -> list[str]:
        """Перевести миссии, где всё доделано, в терминальный статус.

        Возвращает id миссий, статус которых изменился.
        """
        changed: list[str] = []
        for mission in self.sm.active_missions():
            mid = mission["id"]
            if not self.sm.is_mission_settled(mid):
                continue
            counts = self.sm.status_counts(mid)
            needs_human = sum(counts.get(s.value, 0) for s in NEEDS_HUMAN)
            failed = counts.get(TaskStatus.FAILED.value, 0)
            if needs_human:
                target = MissionStatus.BLOCKED
                reason = f"ждёт человека: {needs_human} задач(и)"
            elif failed:
                target = MissionStatus.FAILED
                reason = f"провалено задач: {failed}"
            else:
                target = MissionStatus.DONE
                reason = ""
            if mission["status"] != target.value:
                self.sm.set_mission_status(mid, target, blocked_reason=reason)
                changed.append(mid)
        return changed
