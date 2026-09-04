"""Клиент MCP: чужие инструменты как свои.

Сервер MCP запускается по требованию и живёт, пока идёт работа с ним.
Его инструменты приводятся к тому же ToolSpec, что и встроенные, поэтому
любой провайдер получает их в своём родном формате без отдельного кода.

Реализован транспорт stdio на стандартной библиотеке (JSON-RPC поверх
stdin/stdout процесса): это покрывает подавляющее большинство серверов и
не тянет зависимостей. Если установлен пакет `mcp`, доступен и http.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..errors import CapabilityMissing
from ..providers.base import ToolSpec
from .base import Tool, ToolResult

PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "agentos", "version": "0.1.0"}
DEFAULT_TIMEOUT_S = 30.0


@dataclass
class MCPServerSpec:
    """Описание сервера из config/mcp.json."""

    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    auto: bool = False
    requires_env: list[str] = field(default_factory=list)
    description: str = ""

    @classmethod
    def from_config(cls, name: str, raw: dict[str, Any]) -> MCPServerSpec:
        return cls(
            name=name,
            transport=str(raw.get("transport", "stdio")),
            command=str(raw.get("command", "")),
            args=[str(a) for a in raw.get("args", []) or []],
            url=str(raw.get("url", "")),
            auto=bool(raw.get("auto", False)),
            requires_env=[str(e) for e in raw.get("requires_env", []) or []],
            description=str(raw.get("description", "")),
        )

    def missing_env(self) -> list[str]:
        """Каких секретов не хватает. Их агент не добывает сам — просит человека."""
        return [key for key in self.requires_env if not os.environ.get(key)]

    def executable_missing(self) -> bool:
        return bool(self.command) and shutil.which(self.command) is None


class MCPStdioClient:
    """JSON-RPC поверх stdio дочернего процесса."""

    def __init__(self, spec: MCPServerSpec, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self.spec = spec
        self.timeout_s = timeout_s
        self._proc: subprocess.Popen[str] | None = None
        self._counter = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._proc is not None:
            return
        missing = self.spec.missing_env()
        if missing:
            raise CapabilityMissing(
                "secret",
                ", ".join(missing),
                f"задай переменные окружения для MCP-сервера '{self.spec.name}'",
            )
        if self.spec.executable_missing():
            raise CapabilityMissing(
                "tool",
                self.spec.command,
                f"не найден исполняемый файл '{self.spec.command}' для MCP-сервера"
                f" '{self.spec.name}'",
            )
        self._proc = subprocess.Popen(
            [self.spec.command, *self.spec.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        self._notify("notifications/initialized", {})

    def stop(self) -> None:
        if self._proc is None:
            return
        proc, self._proc = self._proc, None
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    def __enter__(self) -> MCPStdioClient:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # --------------------------------------------------------------- rpc
    def _send(self, payload: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise CapabilityMissing("mcp", self.spec.name, "сервер не запущен")
        proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._counter += 1
            request_id = self._counter
            self._send(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            )
            return self._await(request_id)

    def _await(self, request_id: int) -> dict[str, Any]:
        """Дождаться ответа с нужным id, пропуская уведомления сервера."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            raise CapabilityMissing("mcp", self.spec.name, "сервер не отвечает")
        deadline = time.time() + self.timeout_s
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                raise CapabilityMissing(
                    "mcp", self.spec.name, "сервер закрыл соединение до ответа"
                )
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue  # сервер может писать в stdout мусор при старте
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(
                    f"MCP {self.spec.name}: {message['error'].get('message', 'ошибка')}"
                )
            return message.get("result", {}) or {}
        raise TimeoutError(f"MCP {self.spec.name}: нет ответа за {self.timeout_s}s")

    # -------------------------------------------------------------- api
    def list_tools(self) -> list[dict[str, Any]]:
        return list(self._request("tools/list", {}).get("tools", []) or [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        try:
            result = self._request("tools/call", {"name": name, "arguments": arguments})
        except Exception as exc:
            return ToolResult(False, error=f"{type(exc).__name__}: {exc}")
        chunks = [
            part.get("text", "")
            for part in result.get("content", []) or []
            if part.get("type") == "text"
        ]
        text = "\n".join(c for c in chunks if c)
        is_error = bool(result.get("isError"))
        return ToolResult(not is_error, output=text, error=text if is_error else "")


def mcp_tools_of(client: MCPStdioClient, prefix: str = "") -> list[Tool]:
    """Обернуть инструменты сервера в наши Tool.

    Имя префиксуется именем сервера: два сервера могут звать инструмент
    одинаково, и модель должна различать их однозначно.
    """
    tools: list[Tool] = []
    for raw in client.list_tools():
        name = str(raw.get("name", ""))
        if not name:
            continue
        full_name = f"{prefix or client.spec.name}__{name}"

        def handler(_name: str = name, **arguments: Any) -> ToolResult:
            return client.call_tool(_name, arguments)

        tools.append(
            Tool(
                name=full_name,
                description=str(raw.get("description", "")) or f"MCP {client.spec.name}: {name}",
                input_schema=raw.get("inputSchema")
                or {"type": "object", "properties": {}},
                handler=handler,
                dangerous=True,
            )
        )
    return tools


def specs_of(tools: list[Tool]) -> list[ToolSpec]:
    return [t.spec() for t in tools]
