"""Редакция секретов.

Правило простое: секрет не должен попасть ни в БД, ни в журнал событий,
ни в отчёт субагента. Редактор применяется на выходе всех трёх.
"""

from __future__ import annotations

import os
import re
from typing import Any

#: Маски по умолчанию, если policy.yaml недоступен.
DEFAULT_PATTERNS: tuple[str, ...] = (
    r"sk-[A-Za-z0-9_\-]{16,}",
    r"AIza[0-9A-Za-z_\-]{30,}",
    r"gh[pousr]_[A-Za-z0-9]{20,}",
    r"(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*\S+",
)

#: Имена переменных окружения, значения которых вырезаются целиком.
SECRET_ENV_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")

MASK = "«скрыто»"


class Redactor:
    """Вырезает секреты из произвольных структур перед записью."""

    def __init__(self, patterns: list[str] | tuple[str, ...] | None = None) -> None:
        self._regexes = [re.compile(p) for p in (patterns or DEFAULT_PATTERNS)]
        self._literals = self._collect_env_secrets()

    @staticmethod
    def _collect_env_secrets() -> list[str]:
        """Значения «секретных» переменных окружения — вырезаются буквально."""
        values: list[str] = []
        for name, value in os.environ.items():
            if len(value) < 8:
                continue
            if any(hint in name.upper() for hint in SECRET_ENV_HINTS):
                values.append(value)
        # Длинные — первыми, чтобы подстрока не съела совпадение целого.
        return sorted(set(values), key=len, reverse=True)

    @classmethod
    def from_policy(cls, policy: dict[str, Any]) -> Redactor:
        patterns = (policy.get("secrets") or {}).get("redact_patterns")
        return cls(patterns or None)

    def text(self, value: str) -> str:
        out = value
        for literal in self._literals:
            out = out.replace(literal, MASK)
        for rx in self._regexes:
            out = rx.sub(MASK, out)
        return out

    def apply(self, value: Any) -> Any:
        """Рекурсивно отредактировать строки внутри dict/list/строк."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {k: self.apply(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.apply(v) for v in value]
        return value
