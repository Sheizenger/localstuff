"""Адаптер OpenAI поверх официального SDK (Chat Completions).

Нормализация ошибок здесь та же, что у остальных адаптеров: оркестратору
всё равно, чей это был 429 — важно только, ждать секунды или до сброса окна.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..errors import (
    ContextOverflow,
    ProviderUnavailable,
    QuotaExhausted,
    RateLimited,
    TransientProviderError,
)
from .base import Completion, Message, Provider, ToolCall, ToolSpec, Usage

_QUOTA_HINTS = ("insufficient_quota", "exceeded your current quota", "billing", "credit")
_OVERFLOW_HINTS = ("context_length_exceeded", "maximum context length", "too many tokens")


class OpenAIProvider(Provider):
    name = "openai"
    env_keys = ("OPENAI_API_KEY",)

    def __init__(self) -> None:
        self._client: Any = None

    def available(self) -> bool:
        if not any(os.environ.get(k) for k in self.env_keys):
            return False
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return True

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import openai
        except ImportError as exc:
            raise ProviderUnavailable(
                "не установлен SDK: pip install 'agentos[openai]'", provider=self.name
            ) from exc
        if not os.environ.get("OPENAI_API_KEY"):
            raise ProviderUnavailable("нет OPENAI_API_KEY", provider=self.name)
        self._client = openai.OpenAI()
        return self._client

    # ------------------------------------------------------------ конвертация
    @staticmethod
    def _to_native_messages(messages: list[Message], system: str) -> list[dict[str, Any]]:
        native: list[dict[str, Any]] = []
        if system:
            native.append({"role": "system", "content": system})
        for msg in messages:
            if isinstance(msg.content, str):
                native.append({"role": msg.role, "content": msg.content})
                continue
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in msg.content:
                if block.type == "text" and block.text:
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_calls.append(
                        {
                            "id": block.tool_call_id,
                            "type": "function",
                            "function": {
                                "name": block.tool_name,
                                "arguments": json.dumps(block.arguments, ensure_ascii=False),
                            },
                        }
                    )
                elif block.type == "tool_result":
                    # У OpenAI результат инструмента — отдельное сообщение роли tool.
                    native.append(
                        {
                            "role": "tool",
                            "tool_call_id": block.tool_call_id,
                            "content": block.text,
                        }
                    )
            if text_parts or tool_calls:
                entry: dict[str, Any] = {
                    "role": "assistant" if msg.role == "assistant" else "user",
                    "content": "\n".join(text_parts),
                }
                if tool_calls:
                    entry["tool_calls"] = tool_calls
                native.append(entry)
        return native

    @staticmethod
    def _to_native_tools(tools: list[ToolSpec] | None) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in (tools or [])
        ]

    # ----------------------------------------------------------------- вызов
    def complete(
        self,
        *,
        model: str,
        messages: list[Message],
        system: str = "",
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 4096,
        stop: list[str] | None = None,
    ) -> Completion:
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": self._to_native_messages(messages, system),
            "max_completion_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = self._to_native_tools(tools)
        if stop:
            kwargs["stop"] = stop
        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise self._normalize(exc, model) from exc
        return self._to_completion(response, model)

    def _to_completion(self, response: Any, model: str) -> Completion:
        choice = response.choices[0]
        msg = choice.message
        calls: list[ToolCall] = []
        for call in getattr(msg, "tool_calls", None) or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {"_raw": call.function.arguments}
            calls.append(ToolCall(id=call.id, name=call.function.name, arguments=arguments))
        usage_obj = getattr(response, "usage", None)
        cached = 0
        details = getattr(usage_obj, "prompt_tokens_details", None)
        if details is not None:
            cached = int(getattr(details, "cached_tokens", 0) or 0)
        usage = Usage(
            tokens_in=int(getattr(usage_obj, "prompt_tokens", 0) or 0),
            tokens_out=int(getattr(usage_obj, "completion_tokens", 0) or 0),
            cached_in=cached,
        )
        return Completion(
            text=(msg.content or "").strip(),
            tool_calls=calls,
            usage=usage,
            stop_reason=str(getattr(choice, "finish_reason", "") or ""),
            model=str(getattr(response, "model", model)),
            provider=self.name,
            raw=response,
        )

    def _normalize(self, exc: Exception, model: str) -> Exception:
        try:
            import openai
        except ImportError:
            return TransientProviderError(str(exc), provider=self.name, model=model)

        message = str(getattr(exc, "message", "") or exc)
        lowered = message.lower()
        if isinstance(exc, openai.RateLimitError):
            if any(hint in lowered for hint in _QUOTA_HINTS):
                return QuotaExhausted(message, provider=self.name, model=model)
            retry_after = _retry_after_of(exc)
            return RateLimited(message, retry_after_s=retry_after, provider=self.name, model=model)
        if isinstance(exc, openai.BadRequestError):
            if any(hint in lowered for hint in _OVERFLOW_HINTS):
                return ContextOverflow(message, provider=self.name, model=model)
            return TransientProviderError(message, provider=self.name, model=model)
        if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return ProviderUnavailable(message, provider=self.name, model=model)
        if isinstance(exc, openai.APIStatusError) and (
            int(getattr(exc, "status_code", 0) or 0) == 402
            or any(hint in lowered for hint in _QUOTA_HINTS)
        ):
            return QuotaExhausted(message, provider=self.name, model=model)
        return TransientProviderError(message, provider=self.name, model=model)

    # ------------------------------------------------------------ эмбеддинги
    def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        client = self._get_client()
        try:
            response = client.embeddings.create(model=model, input=texts)
        except Exception as exc:
            raise self._normalize(exc, model) from exc
        return [item.embedding for item in response.data]


def _retry_after_of(exc: Any, default: float = 60.0) -> float:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        raw = headers.get("retry-after") or headers.get("Retry-After")
        if raw:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
    return default
