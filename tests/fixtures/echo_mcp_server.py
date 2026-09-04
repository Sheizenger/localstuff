#!/usr/bin/env python3
"""Минимальный MCP-сервер для тестов: JSON-RPC поверх stdio, один инструмент.

Существует, чтобы MCP-клиент проверялся против реального протокольного
обмена, а не против мока самого себя.
"""

from __future__ import annotations

import json
import sys

TOOLS = [
    {
        "name": "echo",
        "description": "Вернуть переданный текст.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    }
]


def reply(request_id, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = message.get("method", "")
        request_id = message.get("id")
        if request_id is None:
            continue  # уведомление, ответа не требует
        if method == "initialize":
            reply(request_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "echo", "version": "0.1.0"},
            })
        elif method == "tools/list":
            reply(request_id, {"tools": TOOLS})
        elif method == "tools/call":
            params = message.get("params", {})
            text = (params.get("arguments") or {}).get("text", "")
            if params.get("name") != "echo":
                reply(request_id, {
                    "content": [{"type": "text", "text": "нет такого инструмента"}],
                    "isError": True,
                })
            else:
                reply(request_id, {"content": [{"type": "text", "text": f"эхо: {text}"}]})
        else:
            reply(request_id, {})


if __name__ == "__main__":
    main()
