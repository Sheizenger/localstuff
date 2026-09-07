"""Автоподключение возможностей.

Это то место, где «агент сам подключает коннекты, скиллы и доступы».
Логика намеренно простая и проверяемая:

  найдено в каталоге и разрешено политикой -> включаем и записываем;
  нужен секрет или чего-то нет в каталоге  -> CapabilityMissing с точной
  инструкцией человеку, задача уходит в BLOCKED_CAPABILITY, а остальные
  ветки DAG продолжают идти.

Агент не «добывает» доступы сам и не обходит политику — он формулирует
ровно один понятный запрос и продолжает работать над остальным.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..bus import EV_CAPABILITY_REQUEST
from ..errors import CapabilityMissing
from .base import Tool, ToolRegistry, ToolResult
from .mcp_client import MCPServerSpec, MCPStdioClient, mcp_tools_of

KIND_SKILL = "skill"
KIND_MCP = "mcp"
KIND_TOOL = "tool"
KIND_SECRET = "secret"

STATUS_ENABLED = "enabled"
STATUS_BLOCKED = "blocked"
STATUS_REQUESTED = "requested"


@dataclass
class CapabilityStatus:
    kind: str
    name: str
    status: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == STATUS_ENABLED

    def as_line(self) -> str:
        mark = {"enabled": "включено", "blocked": "нужно от человека"}.get(self.status, self.status)
        tail = f" — {self.detail}" if self.detail else ""
        return f"- [{mark}] {self.kind}/{self.name}{tail}"


class CapabilityResolver:
    def __init__(self, runtime: Any) -> None:
        self.rt = runtime
        self._clients: dict[str, MCPStdioClient] = {}

    # ------------------------------------------------------------- каталог
    def catalog(self) -> dict[str, MCPServerSpec]:
        servers = (self.rt.config.mcp or {}).get("servers", {}) or {}
        return {name: MCPServerSpec.from_config(name, raw) for name, raw in servers.items()}

    def list_all(self) -> list[CapabilityStatus]:
        """Что уже подключено и что ждёт человека."""
        rows = self.rt.store.query("SELECT * FROM capabilities ORDER BY kind, name")
        return [CapabilityStatus(r["kind"], r["name"], r["status"], r["detail"]) for r in rows]

    def pending(self) -> list[CapabilityStatus]:
        return [c for c in self.list_all() if c.status == STATUS_BLOCKED]

    # ------------------------------------------------------------- запросы
    def request(
        self, kind: str, name: str, *, reason: str = "", mission_id: str = "", task_id: str = ""
    ) -> CapabilityStatus:
        """Попросить возможность. Включает сам, если можно; иначе блокирует задачу."""
        self.rt.bus.emit(
            EV_CAPABILITY_REQUEST,
            mission_id=mission_id,
            task_id=task_id,
            actor="capability",
            cap_kind=kind,
            name=name,
            reason=reason,
            summary=f"запрошено {kind}/{name}: {reason}",
        )
        if kind == KIND_MCP:
            status = self._resolve_mcp(name, reason)
        elif kind == KIND_SKILL:
            status = self._resolve_skill(name, reason)
        elif kind == KIND_TOOL:
            status = self._resolve_tool(name, reason)
        else:
            status = CapabilityStatus(
                KIND_SECRET,
                name,
                STATUS_BLOCKED,
                reason or f"задай переменную окружения {name} и запусти resume",
            )
        self._record(status, mission_id)
        return status

    def require(self, kind: str, name: str, *, reason: str = "", **kw: Any) -> CapabilityStatus:
        """То же, но недоступность — исключение: задача уходит в BLOCKED_CAPABILITY."""
        status = self.request(kind, name, reason=reason, **kw)
        if not status.ok:
            raise CapabilityMissing(status.kind, status.name, status.detail)
        return status

    # ---------------------------------------------------------------- MCP
    def _resolve_mcp(self, name: str, reason: str) -> CapabilityStatus:
        catalog = self.catalog()
        spec = catalog.get(name)
        if spec is None:
            known = ", ".join(sorted(catalog)) or "каталог пуст"
            return CapabilityStatus(
                KIND_MCP,
                name,
                STATUS_BLOCKED,
                f"сервера нет в config/mcp.json (есть: {known}); добавь его и подтверди",
            )
        if not self.rt.config.get("capability.auto_enable.mcp_servers", True):
            return CapabilityStatus(
                KIND_MCP, name, STATUS_BLOCKED, "автоподключение MCP выключено в конфиге"
            )
        if not spec.auto:
            return CapabilityStatus(
                KIND_MCP,
                name,
                STATUS_BLOCKED,
                "сервер помечен auto:false — нужно подтверждение человека",
            )
        missing = spec.missing_env()
        if missing:
            return CapabilityStatus(
                KIND_MCP,
                name,
                STATUS_BLOCKED,
                f"нет переменных окружения: {', '.join(missing)}",
            )
        try:
            count = len(self.enable_mcp(name))
        except CapabilityMissing as exc:
            return CapabilityStatus(KIND_MCP, name, STATUS_BLOCKED, exc.how_to_fix)
        except Exception as exc:
            return CapabilityStatus(KIND_MCP, name, STATUS_BLOCKED, f"{type(exc).__name__}: {exc}")
        return CapabilityStatus(KIND_MCP, name, STATUS_ENABLED, f"подключено инструментов: {count}")

    def enable_mcp(self, name: str) -> list[Tool]:
        """Поднять сервер и зарегистрировать его инструменты в реестре.

        Серверы поднимаются по требованию, а не на старте: иначе каждый
        запуск платил бы за инициализацию всех серверов каталога.
        """
        spec = self.catalog().get(name)
        if spec is None:
            raise CapabilityMissing(KIND_MCP, name, "сервера нет в config/mcp.json")
        client = self._clients.get(name)
        if client is None:
            client = MCPStdioClient(spec)
            client.start()
            self._clients[name] = client
        tools = mcp_tools_of(client)
        self.rt.tools.register_all(tools)
        return tools

    def shutdown(self) -> None:
        for client in self._clients.values():
            client.stop()
        self._clients.clear()

    # -------------------------------------------------------------- навыки
    def _resolve_skill(self, name: str, reason: str) -> CapabilityStatus:
        skill = self.rt.skills.load(name)
        if skill is not None:
            return CapabilityStatus(KIND_SKILL, name, STATUS_ENABLED, "навык найден")
        proposed = self.rt.skills.skills_dir / "_proposed" / name / "SKILL.md"
        if proposed.exists():
            return CapabilityStatus(
                KIND_SKILL,
                name,
                STATUS_BLOCKED,
                "навык есть только как черновик: agentctl skill promote " + name,
            )
        return CapabilityStatus(
            KIND_SKILL,
            name,
            STATUS_BLOCKED,
            f"навыка нет; можно создать: skills/{name}/SKILL.md",
        )

    def _resolve_tool(self, name: str, reason: str) -> CapabilityStatus:
        if self.rt.tools.get(name) is not None:
            return CapabilityStatus(KIND_TOOL, name, STATUS_ENABLED, "инструмент доступен")
        # Инструмент MCP-сервера адресуется как "<сервер>__<инструмент>".
        if "__" in name:
            server = name.split("__", 1)[0]
            status = self._resolve_mcp(server, reason)
            if status.ok and self.rt.tools.get(name) is not None:
                return CapabilityStatus(KIND_TOOL, name, STATUS_ENABLED, "подключён через MCP")
            return CapabilityStatus(KIND_TOOL, name, STATUS_BLOCKED, status.detail)
        return CapabilityStatus(KIND_TOOL, name, STATUS_BLOCKED, f"инструмента нет: {name}")

    # ------------------------------------------------------------- хранение
    def _record(self, status: CapabilityStatus, mission_id: str = "") -> None:
        with self.rt.store.tx() as conn:
            conn.execute(
                "INSERT INTO capabilities(name, kind, status, detail, mission_id, updated_at)"
                " VALUES(?,?,?,?,?,?) ON CONFLICT(kind, name) DO UPDATE SET"
                " status=excluded.status, detail=excluded.detail, updated_at=excluded.updated_at",
                (
                    status.name,
                    status.kind,
                    status.status,
                    status.detail,
                    mission_id,
                    time.time(),
                ),
            )


def build_capability_tools(resolver: CapabilityResolver) -> list[Tool]:
    """Инструмент, которым агент просит возможность прямо посреди задачи."""

    def capability_request(kind: str, name: str, reason: str = "") -> ToolResult:
        status = resolver.request(kind, name, reason=reason)
        if status.ok:
            return ToolResult(
                True, output=f"подключено: {status.kind}/{status.name}. {status.detail}"
            )
        # Не ошибка исполнения, а сигнал оркестратору: задача ждёт человека.
        raise CapabilityMissing(status.kind, status.name, status.detail)

    def capability_list() -> ToolResult:
        items = resolver.list_all()
        if not items:
            return ToolResult(True, output="(ничего не подключалось)")
        return ToolResult(True, output="\n".join(i.as_line() for i in items))

    return [
        Tool(
            name="capability_request",
            description=(
                "Запросить возможность: MCP-сервер, навык, инструмент или секрет."
                " Если её нельзя включить автоматически, задача встанет в ожидание"
                " человека, а остальные ветки работы продолжатся."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["mcp", "skill", "tool", "secret"]},
                    "name": {"type": "string"},
                    "reason": {"type": "string", "description": "зачем это нужно"},
                },
                "required": ["kind", "name"],
            },
            handler=capability_request,
        ),
        Tool(
            name="capability_list",
            description="Показать, что уже подключено и что ждёт человека.",
            input_schema={"type": "object", "properties": {}},
            handler=capability_list,
        ),
    ]


def register_into(registry: ToolRegistry, resolver: CapabilityResolver) -> None:
    registry.register_all(build_capability_tools(resolver))
