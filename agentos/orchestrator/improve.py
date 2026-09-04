"""Самоулучшение: превратить прошедший прогон в знание и навыки.

Без этого шага система каждый раз начинает с нуля: одни и те же грабли,
одни и те же вопросы к человеку. Здесь эпизоды сжимаются в факты и уроки,
а повторяющиеся удачные процедуры оформляются в черновики навыков.

Черновик навыка НЕ становится активным автоматически, пока это не
разрешено в конфиге: самопишущийся навык, попавший в контекст всех
будущих задач, — самый дорогой способ закрепить ошибку.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..bus import EV_MEMORY_WRITE, EV_SKILL_PROPOSED
from ..errors import ProviderUnavailable, QuotaExhausted
from ..memory.semantic import KIND_FACT, KIND_LESSON
from ..memory.working import GOAL_MARKER, SCHEMA_MARKER, truncate_to_tokens
from ..providers.base import Message
from ..runtime import Runtime

SKILL_TEMPLATE = """---
name: {name}
description: {description}
triggers: [{triggers}]
status: proposed
version: 1
---

# {title}

{body}

## Когда применять

{when}

## Проверка результата

{check}
"""


@dataclass
class ConsolidationResult:
    facts: list[str] = field(default_factory=list)
    lessons: list[str] = field(default_factory=list)
    proposed_skills: list[str] = field(default_factory=list)
    promoted_skills: list[str] = field(default_factory=list)


class Improver:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    # -------------------------------------------------------------- основное
    def consolidate(self, mission_id: str) -> ConsolidationResult:
        """Сжать прогон в знание. Вызывается по завершении миссии."""
        result = ConsolidationResult()
        payload = self._distill(mission_id)

        for item in payload.get("facts", []) or []:
            fact_id = self.rt.semantic.add(
                str(item.get("content", "")),
                kind=KIND_FACT,
                subject=str(item.get("subject", "")),
                source=f"миссия {mission_id}",
                confidence=0.7,
                mission_id=mission_id,
            )
            if fact_id:
                result.facts.append(fact_id)

        for item in payload.get("lessons", []) or []:
            fact_id = self.rt.semantic.add(
                str(item.get("content", item) if isinstance(item, dict) else item),
                kind=KIND_LESSON,
                subject=str(item.get("subject", "")) if isinstance(item, dict) else "",
                source=f"миссия {mission_id}",
                confidence=0.6,
                mission_id=mission_id,
            )
            if fact_id:
                result.lessons.append(fact_id)

        for candidate in payload.get("skill_candidates", []) or []:
            name = self._slug(str(candidate.get("name", "")))
            if not name:
                continue
            path = self.propose_skill(
                name=name,
                description=str(candidate.get("description", "")),
                triggers=[str(t) for t in candidate.get("triggers", []) or []],
                body=str(candidate.get("body", "")),
                when=str(candidate.get("when", "")),
                check=str(candidate.get("check", "")),
                mission_id=mission_id,
            )
            if path:
                result.proposed_skills.append(name)

        if self.rt.config.get("improve.auto_promote_skills", False):
            for name in result.proposed_skills:
                if self.promote_skill(name):
                    result.promoted_skills.append(name)

        self.rt.sync_skills()
        self.rt.bus.emit(
            EV_MEMORY_WRITE,
            mission_id=mission_id,
            actor="scribe",
            facts=len(result.facts),
            lessons=len(result.lessons),
            skills_proposed=result.proposed_skills,
            summary=f"консолидация: {len(result.facts)} фактов, {len(result.lessons)} уроков",
        )
        return result

    # ------------------------------------------------------------- извлечение
    def _distill(self, mission_id: str) -> dict[str, Any]:
        """Спросить модель. Без модели — детерминированный минимум фактов."""
        route = self.rt.router.try_pick(self.rt.config.role("scribe").tier)
        if route is None:
            return self._heuristic(mission_id)

        mission = self.rt.sm.get_mission(mission_id) or {}
        digest = self.rt.episodic.digest(mission_id)
        results = "\n".join(
            f"- {title}: {text[:300]}"
            for title, text in (
                (r["title"], r["result"] or "")
                for r in self.rt.store.query(
                    "SELECT title, result FROM tasks WHERE mission_id=? AND status='DONE'",
                    (mission_id,),
                )
            )
        )
        role = self.rt.config.role("scribe")
        prompt = truncate_to_tokens(
            f"{GOAL_MARKER} {mission.get('goal', '')}\n\n"
            f"РЕЗУЛЬТАТЫ ЗАДАЧ:\n{results or '(нет)'}\n\n"
            f"ХОД РАБОТЫ:\n{digest}\n\n"
            f"{SCHEMA_MARKER} lessons\n"
            'Верни JSON: {"facts": [{subject, content}], "lessons": [{subject, content}], '
            '"skill_candidates": [{name, description, triggers[], body, when, check}]}',
            8000,
        )
        try:
            completion = route.provider.complete(
                model=route.spec.id,
                messages=[Message.user(prompt)],
                system=role.system,
                max_tokens=min(role.max_output_tokens, route.spec.max_output),
            )
        except (QuotaExhausted, ProviderUnavailable):
            return self._heuristic(mission_id)
        self.rt.ledger.record(
            provider=route.spec.provider,
            model=route.spec.id,
            tokens_in=completion.usage.tokens_in,
            tokens_out=completion.usage.tokens_out,
            mission_id=mission_id,
            kind="consolidate",
        )
        payload = completion.json()
        return payload if isinstance(payload, dict) else self._heuristic(mission_id)

    def _heuristic(self, mission_id: str) -> dict[str, Any]:
        """Что можно записать без модели: факт о самой выполненной цели."""
        mission = self.rt.sm.get_mission(mission_id) or {}
        goal = mission.get("goal", "")
        if not goal:
            return {}
        spend = self.rt.ledger.mission_spend(mission_id)
        return {
            "facts": [
                {
                    "subject": "выполненные цели",
                    "content": f"цель «{goal}» выполнена; расход {spend.tokens} токенов",
                }
            ],
            "lessons": [],
            "skill_candidates": [],
        }

    # ---------------------------------------------------------------- навыки
    def propose_skill(
        self,
        *,
        name: str,
        description: str,
        triggers: list[str],
        body: str,
        when: str = "",
        check: str = "",
        mission_id: str = "",
    ) -> Path | None:
        """Записать черновик навыка в skills/_proposed/<name>/SKILL.md."""
        if not name or not body.strip():
            return None
        target = self.rt.skills.skills_dir / "_proposed" / name
        target.mkdir(parents=True, exist_ok=True)
        path = target / "SKILL.md"
        path.write_text(
            SKILL_TEMPLATE.format(
                name=name,
                description=description or f"навык {name}",
                triggers=", ".join(triggers),
                title=name.replace("-", " ").capitalize(),
                body=body.strip(),
                when=when.strip() or "Когда задача повторяет описанный сценарий.",
                check=check.strip() or "Результат соответствует критериям приёмки миссии.",
            ),
            encoding="utf-8",
        )
        self.rt.bus.emit(
            EV_SKILL_PROPOSED,
            mission_id=mission_id,
            actor="scribe",
            name=name,
            path=str(path),
            summary=f"предложен навык: {name}",
        )
        return path

    def promote_skill(self, name: str) -> bool:
        """Перевести черновик в активные навыки."""
        source = self.rt.skills.skills_dir / "_proposed" / name / "SKILL.md"
        if not source.exists():
            return False
        target_dir = self.rt.skills.skills_dir / name
        target_dir.mkdir(parents=True, exist_ok=True)
        text = source.read_text(encoding="utf-8").replace("status: proposed", "status: active")
        (target_dir / "SKILL.md").write_text(text, encoding="utf-8")
        source.unlink()
        try:
            source.parent.rmdir()
        except OSError:
            pass
        self.rt.sync_skills()
        return True

    def proposed(self) -> list[str]:
        root = self.rt.skills.skills_dir / "_proposed"
        return sorted(p.parent.name for p in root.glob("*/SKILL.md")) if root.exists() else []

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^\w\-]+", "-", value.strip().lower()).strip("-")
        return slug[:48]

    # ------------------------------------------------------------------ ретро
    def retro(self, mission_id: str) -> list[str]:
        """Уроки из провалов: что ломалось и сколько раз.

        Пишется даже при успехе — повторные попытки внутри успешной миссии
        всё равно означают, что что-то устроено неудобно.
        """
        rows = self.rt.store.query(
            "SELECT title, role, attempts, blocked_reason FROM tasks"
            " WHERE mission_id=? AND (attempts > 1 OR status='FAILED')",
            (mission_id,),
        )
        written: list[str] = []
        for row in rows:
            content = (
                f"задача «{row['title']}» (роль {row['role']}) потребовала"
                f" {row['attempts']} попыток"
                + (f"; причина: {row['blocked_reason']}" if row["blocked_reason"] else "")
            )
            fact_id = self.rt.semantic.add(
                content,
                kind=KIND_LESSON,
                subject="повторные попытки",
                source=f"миссия {mission_id}",
                confidence=0.5,
                mission_id=mission_id,
            )
            if fact_id:
                written.append(fact_id)
        if written:
            self.rt.bus.emit(
                EV_MEMORY_WRITE,
                mission_id=mission_id,
                actor="scribe",
                lessons=len(written),
                summary=f"ретро: {len(written)} уроков о повторных попытках",
            )
        return written

    def _mark_skill_outcomes(self, mission_id: str, success: bool) -> None:
        """Отметить применённые навыки — по этому растёт их рейтинг."""
        for event in self.rt.bus.of_kind("tool.call", mission_id):
            if event["payload"].get("tool") == "skill_load":
                name = event["payload"].get("args", {}).get("name", "")
                if name:
                    self.rt.skills.record_outcome(name, success=success)
