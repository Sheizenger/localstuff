"""Адаптер Google Gemini поверх google-genai.

Gemini иначе называет роли (`model` вместо `assistant`) и складывает
инструменты в function_declarations — здесь это приводится к общему контракту.
"""

from __future__ import annotations

import os
import time
from typing import Any

from ..errors import (
    ContextOverflow,
    ProviderUnavailable,
    QuotaExhausted,
    RateLimited,
    TransientProviderError,
)
from .base import Completion, Message, Provider, ToolCall, ToolSpec, Usage

_QUOTA_HINTS = ("quota", "resource_exhausted", "billing", "exceeded")
_OVERFLOW_HINTS = ("token count", "context length", "too large", "exceeds the maximum")


class GoogleProvider(Provider):
    name = "google"
    env_keys = ("GOOGLE_API_KEY", "GEMINI_API_KEY")

    def __init__(self) -> None:
        self._client: Any = None

    def available(self) -> bool:
        if not any(os.environ.get(k) for k in self.env_keys):
            return False
        try:
            from google import genai  # noqa: F401
        except ImportError:
            return False
        return True

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from google import genai
        except ImportError as exc:
            raise ProviderUnavailable(
                "не установлен SDK: pip install 'agentos[google]'", provider=self.name
            ) from exc
        api_key = next((os.environ.get(k) for k in self.env_keys if os.environ.get(k)), None)
        if not api_key:
            raise ProviderUnavailable("нет GOOGLE_API_KEY", provider=self.name)
        self._client = genai.Client(api_key=api_key)
        return self._client

    # ------------------------------------------------------------ конвертация
    @staticmethod
    def _to_contents(messages: list[Message]) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        for msg in messages:
            role = "model" if msg.role == "assistant" else "user"
            parts: list[dict[str, Any]] = []
            for block in msg.blocks():
                if block.type == "text" and block.text:
                    parts.append({"text": block.text})
                elif block.type == "tool_use":
                    parts.append(
                        {"function_call": {"name": block.tool_name, "args": block.arguments}}
                    )
                elif block.type == "tool_result":
                    parts.append(
                        {
                            "function_response": {
                                "name": block.tool_name or block.tool_call_id,
                                "response": {"output": block.text},
                            }
                        }
                    )
            if parts:
                contents.append({"role": role, "parts": parts})
        return contents

    @staticmethod
    def _to_native_tools(tools: list[ToolSpec] | None) -> list[dict[str, Any]]:
        if not tools:
            return []
        return [
            {
                "function_declarations": [
                    {"name": t.name, "description": t.description, "parameters": t.input_schema}
                    for t in tools
                ]
            }
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
        config: dict[str, Any] = {"max_output_tokens": max_tokens}
        if system:
            config["system_instruction"] = system
        if tools:
            config["tools"] = self._to_native_tools(tools)
        if stop:
            config["stop_sequences"] = stop
        try:
            response = client.models.generate_content(
                model=model, contents=self._to_contents(messages), config=config
            )
        except Exception as exc:
            raise self._normalize(exc, model) from exc
        return self._to_completion(response, model)

    def _to_completion(self, response: Any, model: str) -> Completion:
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for index, candidate in enumerate(getattr(response, "candidates", None) or []):
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                if getattr(part, "text", None):
                    text_parts.append(part.text)
                fn = getattr(part, "function_call", None)
                if fn is not None:
                    calls.append(
                        ToolCall(
                            id=f"call_{index}_{len(calls)}",
                            name=fn.name,
                            arguments=dict(getattr(fn, "args", {}) or {}),
                        )
                    )
        meta = getattr(response, "usage_metadata", None)
        usage = Usage(
            tokens_in=int(getattr(meta, "prompt_token_count", 0) or 0),
            tokens_out=int(getattr(meta, "candidates_token_count", 0) or 0),
            cached_in=int(getattr(meta, "cached_content_token_count", 0) or 0),
        )
        return Completion(
            text="\n".join(text_parts).strip(),
            tool_calls=calls,
            usage=usage,
            stop_reason="",
            model=model,
            provider=self.name,
            raw=response,
        )

    def _normalize(self, exc: Exception, model: str) -> Exception:
        message = str(exc)
        lowered = message.lower()
        status = int(getattr(exc, "code", 0) or getattr(exc, "status_code", 0) or 0)
        if status == 429 or "429" in message or "resource_exhausted" in lowered:
            if any(hint in lowered for hint in _QUOTA_HINTS):
                return QuotaExhausted(
                    message, reset_at=time.time() + 3600, provider=self.name, model=model
                )
            return RateLimited(message, retry_after_s=60.0, provider=self.name, model=model)
        if any(hint in lowered for hint in _OVERFLOW_HINTS):
            return ContextOverflow(message, provider=self.name, model=model)
        if status in (401, 403) or "api key" in lowered:
            return ProviderUnavailable(message, provider=self.name, model=model)
        return TransientProviderError(message, provider=self.name, model=model)

    # ------------------------------------------------------------ эмбеддинги
    def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        client = self._get_client()
        try:
            response = client.models.embed_content(model=model, contents=texts)
        except Exception as exc:
            raise self._normalize(exc, model) from exc
        return [list(item.values) for item in response.embeddings]
