"""MCP-сервер AgentOS: настоящий протокольный обмен, без сети."""

from __future__ import annotations

import pytest

from agentos.contract import render_instructions
from agentos.mcp_server import PROTOCOL_VERSION, AgentOSServer


@pytest.fixture
def server(runtime):
    return AgentOSServer(runtime_factory=lambda: runtime)


def call(server, method, params=None, request_id=1):
    return server.handle(
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
    )


def tool(server, name, **arguments):
    response = call(server, "tools/call", {"name": name, "arguments": arguments})
    result = response["result"]
    return result["content"][0]["text"], result.get("isError", False)


def test_handshake_carries_the_contract(server):
    result = call(server, "initialize")["result"]

    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == "agentos"
    # Контракт уезжает хосту рукопожатием, а не надеждой, что он прочтёт файл.
    assert result["instructions"] == render_instructions()
    assert "agentos_resume" in result["instructions"]


def test_notifications_get_no_response(server):
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_are_listed_with_schemas(server):
    tools = call(server, "tools/list")["result"]["tools"]
    names = {t["name"] for t in tools}

    assert {"agentos_resume", "agentos_goal", "agentos_task_report"} <= names
    for spec in tools:
        assert spec["description"]
        assert spec["inputSchema"]["type"] == "object"

    goal = next(t for t in tools if t["name"] == "agentos_goal")
    assert goal["inputSchema"]["required"] == ["goal"]


def test_goal_then_report_then_verify(server, runtime):
    text, is_error = tool(server, "agentos_goal", goal="собрать обзор проекта")
    assert not is_error
    assert "миссия m_" in text

    mission_id = next(
        line.split()[1] for line in text.splitlines() if line.startswith("миссия ")
    ).rstrip(":")

    # Отдельная открытая задача: часть плана mock-прогон закрывает сам.
    task_id = runtime.sm.add_task(mission_id, title="дописать обзор", role="coder")
    text, is_error = tool(
        server, "agentos_task_report", task_id=task_id, summary="сделано", findings=["раз"]
    )
    assert not is_error

    text, is_error = tool(
        server, "agentos_verify", mission_id=mission_id, verdict="accept", reason="проверено"
    )
    assert not is_error
    assert "критери" in text


def test_memory_tools_route_by_kind(server, runtime):
    tool(server, "agentos_memory_write", content="Сборка идёт через uv", kind="fact")
    tool(server, "agentos_memory_write", content="Гейт не переспорить", kind="lesson")

    text, is_error = tool(server, "agentos_memory_search", query="сборка гейт")

    assert not is_error
    assert "uv" in text or "Гейт" in text


def test_unknown_tool_is_an_error_result_not_a_crash(server):
    text, is_error = tool(server, "agentos_несуществующий")

    assert is_error
    assert "нет такого инструмента" in text


def test_bad_arguments_are_reported_to_the_model(server):
    text, is_error = tool(server, "agentos_task_report", task_id="нет-такой", summary="x")

    assert is_error
    assert "нет такой задачи" in text


def test_closed_task_cannot_be_overwritten(server, runtime):
    """Понятный отказ вместо трассировки: результат уже принят."""
    from agentos.state.machine import TaskStatus

    mission_id = runtime.sm.create_mission("миссия")
    task_id = runtime.sm.add_task(mission_id, title="задача", role="coder")
    runtime.sm.transition(task_id, TaskStatus.RUNNING)
    runtime.sm.transition(task_id, TaskStatus.DONE, result="готово")

    text, is_error = tool(server, "agentos_task_report", task_id=task_id, summary="ещё раз")

    assert is_error
    assert "уже закрыта" in text


def test_stray_stdout_does_not_corrupt_the_protocol(server, monkeypatch):
    """stdout — канал протокола: посторонняя печать сломала бы JSON-RPC."""
    import agentos.mcp_server as module

    def noisy(rt, **kwargs):
        print("посторонний вывод из библиотеки")
        return "результат"

    monkeypatch.setitem(module._build_tools.__globals__, "_tool_status", noisy)
    server._tools["agentos_status"]["handler"] = noisy

    text, is_error = tool(server, "agentos_status")

    assert not is_error
    assert "результат" in text
    assert "посторонний вывод" in text, "перехваченный вывод не теряется, а уходит в текст"


def test_malformed_input_line_is_ignored(server):
    assert server.handle_line("{это не json}") is None


def test_server_survives_a_failing_tool(server, monkeypatch):
    def boom(rt, **kwargs):
        raise RuntimeError("внутренний сбой")

    server._tools["agentos_status"]["handler"] = boom
    text, is_error = tool(server, "agentos_status")

    assert is_error
    assert "внутренний сбой" in text
    # Сервер продолжает отвечать после сбоя инструмента.
    assert call(server, "ping")["result"] == {}
