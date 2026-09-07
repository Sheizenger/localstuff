"""Файловые инструменты. Каждый путь проходит через PolicyGuard."""

from __future__ import annotations

from pathlib import Path

from ..policy.guard import PolicyGuard
from .base import Tool, ToolResult

MAX_LIST_ENTRIES = 400


def build_fs_tools(guard: PolicyGuard, root: Path) -> list[Tool]:
    def _resolve(path: str) -> Path:
        candidate = Path(path)
        return candidate if candidate.is_absolute() else (root / candidate)

    def fs_read(path: str, max_bytes: int = 0) -> ToolResult:
        target = guard.check_read(_resolve(path))
        if not target.exists():
            return ToolResult(False, error=f"файл не найден: {path}")
        if target.is_dir():
            return ToolResult(False, error=f"это каталог, не файл: {path}")
        limit = max_bytes or guard.max_file_bytes()
        data = target.read_bytes()[:limit]
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return ToolResult(False, error="файл не в UTF-8")
        return ToolResult(True, output=text, meta={"bytes": len(data), "path": str(target)})

    def fs_write(path: str, content: str) -> ToolResult:
        target = guard.check_write(_resolve(path))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return ToolResult(
            True, output=f"записано {len(content)} символов в {path}", meta={"path": str(target)}
        )

    def fs_list(path: str = ".", pattern: str = "*") -> ToolResult:
        target = guard.check_read(_resolve(path))
        if not target.is_dir():
            return ToolResult(False, error=f"не каталог: {path}")
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in target.glob(pattern))
        clipped = entries[:MAX_LIST_ENTRIES]
        note = "" if len(entries) == len(clipped) else f"\n…ещё {len(entries) - len(clipped)}"
        return ToolResult(True, output="\n".join(clipped) + note, meta={"count": len(entries)})

    return [
        Tool(
            name="fs_read",
            description="Прочитать текстовый файл проекта.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "путь относительно корня проекта"},
                    "max_bytes": {"type": "integer", "description": "ограничение размера"},
                },
                "required": ["path"],
            },
            handler=fs_read,
        ),
        Tool(
            name="fs_write",
            description="Записать текстовый файл. Пути вне allowlist требуют подтверждения.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            handler=fs_write,
            dangerous=True,
        ),
        Tool(
            name="fs_list",
            description="Список файлов в каталоге по маске.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "pattern": {"type": "string"}},
            },
            handler=fs_list,
        ),
    ]
