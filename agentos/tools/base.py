"""Контракт инструмента и реестр.

Инструмент — это функция с JSON-схемой аргументов. Схема идёт провайдеру
как ToolSpec, поэтому один и тот же инструмент работает с любым из них.
Каждый вызов проходит через PolicyGuard и попадает в журнал событий.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..bus import EV_TOOL_CALL, EventBus
from ..errors import ApprovalRequired, CapabilityMissing, PolicyDenied
from ..providers.base import ToolSpec


@dataclass
class ToolResult:
    """Результат вызова. Ошибка — тоже результат: модель должна её увидеть."""

    ok: bool
    output: str = ""
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def as_text(self) -> str:
        return self.output if self.ok else f"ОШИБКА: {self.error}"


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., ToolResult]
    #: Требует ли инструмент подтверждения человека при первом применении.
    dangerous: bool = False

    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, self.input_schema)


class ToolRegistry:
    """Набор инструментов, доступных конкретной роли."""

    def __init__(self, bus: EventBus | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        self.bus = bus

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def register_all(self, tools: list[Tool]) -> None:
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self, allowed: tuple[str, ...] = ()) -> list[ToolSpec]:
        """Схемы инструментов для провайдера, отфильтрованные ролью."""
        names = [n for n in self.names() if not allowed or n in allowed]
        return [self._tools[n].spec() for n in names]

    def subset(self, allowed: tuple[str, ...]) -> ToolRegistry:
        sub = ToolRegistry(self.bus)
        for name in allowed:
            tool = self._tools.get(name)
            if tool:
                sub.register(tool)
        return sub

    def call(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        mission_id: str = "",
        task_id: str = "",
        actor: str = "",
    ) -> ToolResult:
        """Вызвать инструмент. Наружу не летят исключения — только ToolResult.

        Исключение — ApprovalRequired и CapabilityMissing: их обрабатывает
        оркестратор, переводя задачу в блокировку, а не модель.
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(False, error=f"нет такого инструмента: {name}")
        started = time.time()
        try:
            result = tool.handler(**arguments)
        except (ApprovalRequired, CapabilityMissing):
            raise
        except PolicyDenied as exc:
            result = ToolResult(False, error=str(exc))
        except TypeError as exc:
            result = ToolResult(False, error=f"неверные аргументы: {exc}")
        except Exception as exc:  # инструмент не должен ронять задачу
            result = ToolResult(False, error=f"{type(exc).__name__}: {exc}")
        if self.bus is not None:
            self.bus.emit(
                EV_TOOL_CALL,
                mission_id=mission_id,
                task_id=task_id,
                actor=actor,
                tool=name,
                args=arguments,
                ok=result.ok,
                error=result.error,
                ms=int((time.time() - started) * 1000),
            )
        return result
