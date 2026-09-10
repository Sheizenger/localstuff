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
from ..paths import DEFAULT_AGENT_ID
from ..paths import agent_id as env_agent_id
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


def agent_slug(agent_id: str) -> str:
    """Безопасное для файловой системы имя агента."""
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in agent_id).strip("-")
    return slug or DEFAULT_AGENT_ID


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


class Checkpointer:
    """Снимает состояние миссии на диск после каждого значимого перехода."""

    def __init__(
        self, store: Store, runs_dir: Path, home: Path, agent_id: str = ""
    ) -> None:
        self.store = store
        self.runs_dir = runs_dir
        self.home = home
        #: Чей это чекпоинтер. Мастер-агентов в одном проекте может быть
        #: несколько, и каждый ведёт свой указатель resume.
        self.agent_id = agent_id or env_agent_id()
        self.sm = StateMachine(store)

    # ------------------------------------------------------------------ paths
    def mission_dir(self, mission_id: str) -> Path:
        return self.runs_dir / mission_id

    def state_path(self, mission_id: str) -> Path:
        return self.mission_dir(mission_id) / "state.json"

    def resume_path_for(self, agent_id: str) -> Path:
        """Указатель resume конкретного мастер-агента.

        У агента по умолчанию путь прежний — var/resume.json, его читают
        хуки и скрипты. Остальные агенты пишут рядом, каждый в свой файл:
        иначе два чата в одном проекте затирали бы указатель друг друга.
        """
        if agent_id == DEFAULT_AGENT_ID:
            return self.home / "resume.json"
        return self.home / "agents" / f"resume-{agent_slug(agent_id)}.json"

    @property
    def resume_path(self) -> Path:
        return self.resume_path_for(self.agent_id)

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

    def refresh_resume_pointer(self, agent_id: str | None = None) -> dict[str, Any]:
        """Пересобрать указатель resume: что подхватить в следующей сессии.

        Этот файл — контракт с агент-хостом. Его читает SessionStart-хук и
        инструкция в AGENTS.md, поэтому он должен быть понятен без кода.
        Указатель всегда про одного агента: чужие миссии в него не попадают.
        """
        agent = agent_id or self.agent_id
        missions = self.sm.active_missions(agent)
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
            "agent_id": agent,
            "how_to_continue": "agentctl resume  (или: make resume)",
        }
        atomic_write_json(self.resume_path_for(agent), pointer)
        return pointer

    def refresh_all_pointers(self) -> list[dict[str, Any]]:
        """Обновить указатели всех мастер-агентов, у которых есть работа.

        Нужен там, где проход идёт по всем агентам сразу (`resume --all`):
        иначе указатель чужого агента остался бы с устаревшими счётчиками.
        """
        agents = {row["agent_id"] for row in self.sm.agents_with_work()}
        agents.add(self.agent_id)
        return [self.refresh_resume_pointer(agent) for agent in sorted(agents)]

    # ------------------------------------------------------------------- read
    def load(self, mission_id: str) -> dict[str, Any] | None:
        return read_json(self.state_path(mission_id))

    def resume_pointer(self) -> dict[str, Any]:
        return read_json(self.resume_path, {"has_work": False, "missions": []})

    def unmet_criteria(self, mission_id: str) -> list[str]:
        """Критерии приёмки, которые ещё не подтверждены.

        Таблица dod — источник правды о готовности. Раньше статус миссии
        считался только по задачам, и миссия закрывалась как DONE, даже если
        критерий никто не проверял: вердикт критика молча перезаписывался.
        """
        rows = self.store.query(
            "SELECT criterion, status FROM dod WHERE mission_id=? ORDER BY ord",
            (mission_id,),
        )
        return [r["criterion"] for r in rows if r["status"] not in ("pass", "skipped")]

    def settle_missions(
        self, agent_id: str | None = None, *, all_agents: bool = False
    ) -> list[str]:
        """Перевести миссии, где всё доделано, в терминальный статус.

        По умолчанию трогает только миссии своего мастер-агента.
        Возвращает id миссий, статус которых изменился.
        """
        scope = None if all_agents else (agent_id or self.agent_id)
        changed: list[str] = []
        for mission in self.sm.active_missions(scope):
            mid = mission["id"]
            if not self.sm.is_mission_settled(mid):
                continue
            counts = self.sm.status_counts(mid)
            needs_human = sum(counts.get(s.value, 0) for s in NEEDS_HUMAN)
            failed = counts.get(TaskStatus.FAILED.value, 0)
            unmet = self.unmet_criteria(mid)
            if needs_human:
                target = MissionStatus.BLOCKED
                reason = f"ждёт человека: {needs_human} задач(и)"
            elif failed:
                target = MissionStatus.FAILED
                reason = f"провалено задач: {failed}"
            elif unmet:
                # Задачи кончились, но приёмка не пройдена. «Готово» — это
                # подтверждённые критерии, а не отсутствие оставшейся работы.
                target = MissionStatus.BLOCKED
                reason = "не подтверждены критерии приёмки: " + "; ".join(unmet[:3])
            else:
                target = MissionStatus.DONE
                reason = ""
            if mission["status"] != target.value:
                self.sm.set_mission_status(mid, target, blocked_reason=reason)
                changed.append(mid)
        return changed
