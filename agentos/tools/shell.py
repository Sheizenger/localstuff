"""Запуск команд — только то, что разрешено политикой, и только с таймаутом."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..policy.guard import PolicyGuard
from .base import Tool, ToolResult

#: Сколько символов вывода отдавать модели. Полный лог остаётся в событиях.
MAX_OUTPUT_CHARS = 20000


def run_command(
    command: str, guard: PolicyGuard, cwd: Path, timeout_s: int | None = None
) -> ToolResult:
    """Выполнить команду с проверкой политики. Используется и гейтами."""
    verdict = guard.check_shell(command)
    if not verdict.allowed:
        return ToolResult(False, error=verdict.reason)
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_s or verdict.timeout_s,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(False, error=f"таймаут {timeout_s or verdict.timeout_s}s: {command}")
    except OSError as exc:
        return ToolResult(False, error=f"не удалось запустить: {exc}")

    output = (completed.stdout or "") + (
        f"\n[stderr]\n{completed.stderr}" if completed.stderr else ""
    )
    if len(output) > MAX_OUTPUT_CHARS:
        head = output[: MAX_OUTPUT_CHARS // 2]
        tail = output[-MAX_OUTPUT_CHARS // 2 :]
        output = f"{head}\n…(вывод обрезан)…\n{tail}"
    ok = completed.returncode == 0
    return ToolResult(
        ok,
        output=guard.redact(output),
        error="" if ok else f"код возврата {completed.returncode}",
        meta={"returncode": completed.returncode, "command": command},
    )


def build_shell_tools(guard: PolicyGuard, root: Path) -> list[Tool]:
    def shell(command: str, timeout_s: int = 0) -> ToolResult:
        return run_command(command, guard, root, timeout_s or None)

    return [
        Tool(
            name="shell",
            description=(
                "Выполнить команду в корне проекта. Разрешены только бинари из"
                " allow_binaries политики."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_s": {"type": "integer"},
                },
                "required": ["command"],
            },
            handler=shell,
            dangerous=True,
        )
    ]
