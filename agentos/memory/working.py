"""Рабочая память: сборка контекста под конкретный шаг и его сжатие.

Здесь реализовано главное правило экономии токенов: субагент получает
*бриф*, а не транскрипт главного агента, и возвращает *структурированный
отчёт*, а не свой транскрипт. Контекст главного агента растёт как
(число задач × размер отчёта), а не как сумма всех диалогов.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: Средняя длина токена в символах для смеси кириллицы и латиницы.
#: Точность здесь не нужна: оценка используется для бюджетов и порогов
#: компакции, а фактический расход всегда берётся из usage провайдера.
CHARS_PER_TOKEN = 3.4

#: Маркеры, по которым исполнитель понимает, что от него хотят.
GOAL_MARKER = "ЦЕЛЬ:"
SCHEMA_MARKER = "ФОРМАТ ОТВЕТА:"


def estimate_tokens(text: str) -> int:
    """Грубая оценка числа токенов в тексте."""
    return int(len(text) / CHARS_PER_TOKEN) + 1


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Обрезать текст до бюджета, пометив, что он обрезан."""
    limit = int(max_tokens * CHARS_PER_TOKEN)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 40)].rstrip() + "\n…(обрезано по бюджету контекста)"


@dataclass
class Brief:
    """Всё, что субагент получает на вход. Ничего сверх этого он не видит."""

    mission_goal: str
    task_title: str
    instructions: str = ""
    acceptance: list[str] = field(default_factory=list)
    memory: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    output_schema: str = "report"
    max_report_tokens: int = 1200

    def render(self) -> str:
        parts = [f"{GOAL_MARKER} {self.mission_goal}", f"ЗАДАЧА: {self.task_title}"]
        if self.instructions:
            parts.append(f"ЧТО СДЕЛАТЬ:\n{self.instructions}")
        if self.acceptance:
            parts.append("КРИТЕРИИ ПРИЁМКИ:\n" + "\n".join(f"- {c}" for c in self.acceptance))
        if self.inputs:
            parts.append("ВХОДНЫЕ ДАННЫЕ:\n" + "\n".join(self.inputs))
        if self.memory:
            parts.append("ИЗ ПАМЯТИ ПРОЕКТА:\n" + "\n".join(self.memory))
        if self.skills:
            parts.append(
                "ДОСТУПНЫЕ НАВЫКИ (тело подгружается по запросу):\n" + "\n".join(self.skills)
            )
        if self.constraints:
            parts.append("ОГРАНИЧЕНИЯ:\n" + "\n".join(f"- {c}" for c in self.constraints))
        parts.append(
            f"{SCHEMA_MARKER} {self.output_schema}\n"
            f"Уложись в {self.max_report_tokens} токенов. Верни только результат,"
            " без пересказа своих шагов."
        )
        return "\n\n".join(parts)

    def tokens(self) -> int:
        return estimate_tokens(self.render())


class WorkingMemory:
    """Собирает брифы и сжимает историю."""

    def __init__(
        self,
        config: Any,
        semantic: Any = None,
        episodic: Any = None,
        skills: Any = None,
    ) -> None:
        self.config = config
        self.semantic = semantic
        self.episodic = episodic
        self.skills = skills

    # ------------------------------------------------------------------ сборка
    def build_brief(
        self,
        *,
        mission_goal: str,
        task_title: str,
        instructions: str = "",
        acceptance: list[str] | None = None,
        inputs: list[str] | None = None,
        constraints: list[str] | None = None,
        output_schema: str = "report",
        memory_query: str = "",
        memory_limit: int = 0,
    ) -> Brief:
        """Собрать бриф: цель, критерии, срез памяти и каталог навыков."""
        limit = memory_limit or int(self.config.get("memory.search.top_k", 12))
        query = memory_query or f"{mission_goal} {task_title} {instructions}"

        memory_lines: list[str] = []
        if self.semantic is not None:
            memory_lines = [f.as_line() for f in self.semantic.search(query, limit=limit)]

        skill_lines: list[str] = []
        if self.skills is not None:
            skill_lines = [s.header() for s in self.skills.match(query)]

        return Brief(
            mission_goal=mission_goal,
            task_title=task_title,
            instructions=instructions,
            acceptance=acceptance or [],
            memory=memory_lines,
            skills=skill_lines,
            inputs=inputs or [],
            constraints=constraints or [],
            output_schema=output_schema,
            max_report_tokens=int(self.config.get("budget.subagent_report_tokens", 1200)),
        )

    def fit_brief(self, brief: Brief, max_tokens: int) -> Brief:
        """Ужать бриф под бюджет, отрезая наименее ценное первым.

        Порядок урезания намеренный: сначала навыки (их можно подтянуть
        позже), затем память (её можно перезапросить), и только потом
        входные данные. Цель, критерии и инструкции не режутся никогда —
        без них задача выполняется неверно, а не хуже.
        """
        while brief.tokens() > max_tokens and brief.skills:
            brief.skills.pop()
        while brief.tokens() > max_tokens and brief.memory:
            brief.memory.pop()
        while brief.tokens() > max_tokens and len(brief.inputs) > 1:
            brief.inputs.pop()
        if brief.tokens() > max_tokens and brief.inputs:
            head = max_tokens - estimate_tokens(
                Brief(
                    brief.mission_goal,
                    brief.task_title,
                    brief.instructions,
                    brief.acceptance,
                    output_schema=brief.output_schema,
                ).render()
            )
            brief.inputs = [truncate_to_tokens(brief.inputs[0], max(200, head))]
        return brief

    # ---------------------------------------------------------------- сжатие
    def needs_compaction(self, text: str) -> bool:
        threshold = int(self.config.get("budget.compaction_threshold_tokens", 60000))
        return estimate_tokens(text) > threshold

    @staticmethod
    def handoff_summary(
        *,
        mission_goal: str,
        done: list[str],
        pending: list[str],
        blocked: list[str],
        digest: str = "",
        max_tokens: int = 1500,
    ) -> str:
        """Сводка передачи — то, с чего начинает следующая сессия.

        Формат намеренно человекочитаемый: его читает и агент, и человек,
        когда хочет понять, на чём всё остановилось.
        """
        parts = [f"{GOAL_MARKER} {mission_goal}"]
        if done:
            parts.append("СДЕЛАНО:\n" + "\n".join(f"- {d}" for d in done[:20]))
        if pending:
            parts.append("ОСТАЛОСЬ:\n" + "\n".join(f"- {p}" for p in pending[:20]))
        if blocked:
            parts.append("ЗАБЛОКИРОВАНО:\n" + "\n".join(f"- {b}" for b in blocked[:20]))
        if digest:
            parts.append("ХОД РАБОТЫ (сжато):\n" + digest)
        return truncate_to_tokens("\n\n".join(parts), max_tokens)

    @staticmethod
    def compact_history(messages: list[Any], keep_last: int = 6) -> list[Any]:
        """Заменить середину диалога сводкой, сохранив начало и хвост."""
        if len(messages) <= keep_last + 2:
            return messages
        from ..providers.base import Message

        head = messages[:1]
        tail = messages[-keep_last:]
        middle = messages[1:-keep_last]
        summary = " ".join(
            re.sub(r"\s+", " ", m.as_text())[:200] for m in middle if m.as_text()
        )
        note = Message(
            role="user",
            content=(
                f"[сжато {len(middle)} сообщений] Кратко о пропущенном: "
                f"{truncate_to_tokens(summary, 400)}"
            ),
        )
        return [*head, note, *tail]
