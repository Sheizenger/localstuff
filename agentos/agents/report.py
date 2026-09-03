"""Структурированный отчёт субагента.

Отчёт — единственное, что субагент возвращает наверх. Его размер ограничен
конфигом, поэтому контекст главного агента растёт линейно по числу задач,
а не по объёму работы каждой из них.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..memory.working import estimate_tokens, truncate_to_tokens


@dataclass
class Report:
    summary: str = ""
    findings: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    confidence: float = 0.5
    raw_text: str = ""

    @classmethod
    def parse(cls, payload: Any, fallback_text: str = "") -> Report:
        """Разобрать ответ субагента.

        Модель может вернуть не-JSON. Это не повод терять работу: текст
        становится summary, а уверенность понижается — критик увидит это.
        """
        if isinstance(payload, dict):
            return cls(
                summary=str(payload.get("summary", "")).strip(),
                findings=[str(x) for x in payload.get("findings", []) or []],
                artifacts=[str(x) for x in payload.get("artifacts", []) or []],
                next_steps=[str(x) for x in payload.get("next_steps", []) or []],
                confidence=float(payload.get("confidence", 0.5) or 0.5),
                raw_text=fallback_text,
            )
        text = (fallback_text or str(payload or "")).strip()
        return cls(summary=text, confidence=0.3, raw_text=text)

    def render(self, max_tokens: int = 1200) -> str:
        """Компактное представление для контекста главного агента."""
        parts = [self.summary] if self.summary else []
        if self.findings:
            parts.append("Находки:\n" + "\n".join(f"- {f}" for f in self.findings[:10]))
        if self.artifacts:
            parts.append("Артефакты: " + ", ".join(self.artifacts[:10]))
        if self.next_steps:
            parts.append("Дальше:\n" + "\n".join(f"- {s}" for s in self.next_steps[:10]))
        return truncate_to_tokens("\n\n".join(parts), max_tokens)

    def tokens(self) -> int:
        return estimate_tokens(self.render())

    def is_empty(self) -> bool:
        return not (self.summary or self.findings or self.artifacts)


@dataclass
class Verdict:
    """Вердикт критика по результату задачи или миссии."""

    verdict: str = "needs_human"  # accept | reject | needs_human
    reasons: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    criteria: list[dict[str, Any]] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.verdict == "accept"

    @classmethod
    def parse(cls, payload: Any, fallback_text: str = "") -> Verdict:
        if isinstance(payload, dict):
            value = str(payload.get("verdict", "needs_human")).lower().strip()
            if value not in {"accept", "reject", "needs_human"}:
                value = "needs_human"
            return cls(
                verdict=value,
                reasons=[str(x) for x in payload.get("reasons", []) or []],
                next_actions=[str(x) for x in payload.get("next_actions", []) or []],
                criteria=list(payload.get("criteria", []) or []),
            )
        # Нераспознанный ответ критика — не «принято». Молчание не согласие.
        return cls(verdict="needs_human", reasons=[fallback_text[:400]] if fallback_text else [])

    def render(self) -> str:
        parts = [f"вердикт: {self.verdict}"]
        if self.reasons:
            parts.append("причины:\n" + "\n".join(f"- {r}" for r in self.reasons))
        if self.next_actions:
            parts.append("что сделать:\n" + "\n".join(f"- {a}" for a in self.next_actions))
        return "\n".join(parts)
