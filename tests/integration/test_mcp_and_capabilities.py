"""MCP-клиент против настоящего протокольного обмена и резолвер возможностей.

Мок самого себя ничего не доказывает, поэтому клиент разговаривает с
реальным процессом-сервером из tests/fixtures/echo_mcp_server.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agentos.tools.mcp_client import MCPServerSpec, MCPStdioClient, mcp_tools_of

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ECHO_SERVER = REPO_ROOT / "tests" / "fixtures" / "echo_mcp_server.py"


@pytest.fixture
def echo_client():
    spec = MCPServerSpec(
        name="echo", command=sys.executable, args=[str(ECHO_SERVER)], auto=True
    )
    client = MCPStdioClient(spec)
    client.start()
    yield client
    client.stop()


def test_handshake_and_tool_discovery(echo_client):
    tools = echo_client.list_tools()
    assert [t["name"] for t in tools] == ["echo"]
    assert tools[0]["inputSchema"]["properties"]["text"]["type"] == "string"


def test_mcp_tools_become_ordinary_tools(echo_client):
    """Инструмент MCP должен быть неотличим от встроенного для любого провайдера."""
    tools = mcp_tools_of(echo_client)

    assert tools[0].name == "echo__echo", "имя префиксуется сервером против коллизий"
    spec = tools[0].spec()
    assert spec.input_schema["required"] == ["text"]

    result = tools[0].handler(text="привет")
    assert result.ok
    assert result.output == "эхо: привет"


def test_server_error_is_a_result_not_an_exception(echo_client):
    """Модель должна увидеть ошибку инструмента, а не потерять задачу."""
    result = echo_client.call_tool("несуществующий", {})
    assert not result.ok
    assert result.error


def test_missing_executable_asks_the_human(tmp_path):
    spec = MCPServerSpec(name="призрак", command="нет-такого-бинаря", auto=True)
    client = MCPStdioClient(spec)

    from agentos.errors import CapabilityMissing

    with pytest.raises(CapabilityMissing) as excinfo:
        client.start()
    assert "нет-такого-бинаря" in str(excinfo.value)


def test_missing_secret_is_reported_before_launch(monkeypatch):
    spec = MCPServerSpec(
        name="github", command=sys.executable, requires_env=["ТЕСТОВЫЙ_ТОКЕН"], auto=True
    )
    monkeypatch.delenv("ТЕСТОВЫЙ_ТОКЕН", raising=False)
    assert spec.missing_env() == ["ТЕСТОВЫЙ_ТОКЕН"]


def test_resolver_blocks_instead_of_dead_ending(runtime):
    """Нехватка возможности — не тупик, а один точный запрос человеку."""
    resolver = runtime.capabilities

    not_in_catalog = resolver.request("mcp", "notion", reason="база знаний")
    assert not not_in_catalog.ok
    assert "config/mcp.json" in not_in_catalog.detail

    needs_human = resolver.request("mcp", "github", reason="нужны PR")
    assert not needs_human.ok
    assert "подтверждение" in needs_human.detail

    secret = resolver.request("secret", "STRIPE_KEY", reason="оплата")
    assert not secret.ok

    pending = resolver.pending()
    assert {p.name for p in pending} >= {"notion", "github", "STRIPE_KEY"}


def test_resolver_finds_existing_skill(runtime):
    runtime.sync_skills()
    name = runtime.skills.catalog()[0].name

    status = runtime.capabilities.request("skill", name)

    assert status.ok
    assert runtime.store.one(
        "SELECT status FROM capabilities WHERE kind='skill' AND name=?", (name,)
    )["status"] == "enabled"


def test_capability_request_tool_blocks_the_task(runtime):
    """Инструмент должен уводить задачу в BLOCKED_CAPABILITY, а не врать модели."""
    from agentos.errors import CapabilityMissing

    with pytest.raises(CapabilityMissing):
        runtime.tools.call("capability_request", {"kind": "mcp", "name": "notion"})
