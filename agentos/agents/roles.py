"""Подбор роли под задачу.

«Субагенты подтягиваются автоматически» означает ровно это: планировщик
называет роль, а если он ошибся или роль не указана — роль выбирается по
триггерам из config/agents/*.yaml. Правка ролей не требует правки кода.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import Config, RoleSpec

#: Роль по умолчанию, если ничего не подошло.
FALLBACK_ROLE = "researcher"


@dataclass(frozen=True)
class RoleMatch:
    role: RoleSpec
    score: float
    why: str


class RoleRouter:
    def __init__(self, config: Config) -> None:
        self.config = config

    def resolve(self, name: str) -> RoleSpec | None:
        return self.config.roles.get(name)

    def match(self, text: str, *, limit: int = 3) -> list[RoleMatch]:
        """Ранжировать роли по тексту задачи."""
        lowered = text.lower()
        words = set(re.findall(r"\w+", lowered))
        matches: list[RoleMatch] = []
        for role in self.config.selectable_roles():
            hits = [t for t in role.triggers if t.lower() in lowered or t.lower() in words]
            if not hits:
                continue
            # Приоритетная роль при равном числе попаданий выигрывает.
            score = len(hits) + (9 - role.priority_rank) * 0.01
            matches.append(RoleMatch(role, score, f"триггеры: {', '.join(hits)}"))
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:limit]

    def pick(self, text: str, *, hint: str = "") -> RoleSpec:
        """Выбрать роль: подсказка планировщика важнее триггеров."""
        if hint:
            role = self.resolve(hint)
            if role is not None:
                return role
        matches = self.match(text)
        if matches:
            return matches[0].role
        return self.config.role(FALLBACK_ROLE)

    def catalog_lines(self) -> list[str]:
        """Каталог ролей для промпта планировщика."""
        lines = []
        for role in self.config.selectable_roles():
            triggers = f" — берётся при: {', '.join(role.triggers)}" if role.triggers else ""
            lines.append(f"- {role.name} ({role.tier}, {role.priority}): {role.goal}{triggers}")
        return lines
