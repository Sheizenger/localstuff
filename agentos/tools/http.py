"""HTTP-инструмент на стандартной библиотеке.

Без внешних зависимостей намеренно: ядро должно ставиться и работать
там, где ничего, кроме python, нет.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request

from ..errors import PolicyDenied
from ..policy.guard import PolicyGuard
from .base import Tool, ToolResult

MAX_BODY_CHARS = 40000
USER_AGENT = "AgentOS/0.1 (+autonomous agent)"


def build_http_tools(guard: PolicyGuard) -> list[Tool]:
    def http_get(url: str, timeout_s: int = 30) -> ToolResult:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return ToolResult(False, error=f"неподдерживаемая схема: {parsed.scheme}")
        try:
            guard.check_host(parsed.hostname or "")
        except PolicyDenied as exc:
            return ToolResult(False, error=str(exc))
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                raw = response.read(MAX_BODY_CHARS * 4)
                charset = response.headers.get_content_charset() or "utf-8"
                status = response.status
        except urllib.error.HTTPError as exc:
            return ToolResult(False, error=f"HTTP {exc.code}: {exc.reason}")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return ToolResult(False, error=f"сетевая ошибка: {exc}")
        text = raw.decode(charset, errors="replace")[:MAX_BODY_CHARS]
        return ToolResult(True, output=guard.redact(text), meta={"status": status, "url": url})

    return [
        Tool(
            name="http_get",
            description="Загрузить страницу или API-ответ по URL с учётом сетевой политики.",
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}, "timeout_s": {"type": "integer"}},
                "required": ["url"],
            },
            handler=http_get,
        )
    ]
