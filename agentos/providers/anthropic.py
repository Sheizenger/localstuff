"""Адаптер Anthropic (Claude) поверх официального SDK.

Особенности, которые здесь важны для системы в целом:
  * адаптивное мышление включается для моделей, которые его поддерживают;
  * системный префикс помечается cache_control — это прямая экономия токенов
    при веерном запуске субагентов с одинаковым префиксом;
  * ошибки нормализуются, отдельно выделяется исчерпание квоты — на нём
    держится авто-resume.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

from ..errors import (
    ContextOverflow,
    ProviderUnavailable,
    QuotaExhausted,
    RateLimited,
    TransientProviderError,
)
from .base import Completion, ContentBlock, Message, Provider, ToolCall, ToolSpec, Usage

#: Признаки того, что кончилась квота/баланс, а не сработал обычный rate limit.
_QUOTA_HINTS = ("credit balance", "quota", "billing", "insufficient", "spend limit")
_OVERFLOW_HINTS = ("prompt is too long", "context window", "max_tokens", "too many tokens")

#: Порог, выше которого SDK требует стрима, чтобы не упереться в HTTP-таймаут.
_STREAM_ABOVE_TOKENS = 16000


class AnthropicProvider(Provider):
    name = "anthropic"
    env_keys = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

    def __init__(self) -> None:
        self._client: Any = None

    # ------------------------------------------------------------- lifecycle
    def available(self) -> bool:
        if not any(os.environ.get(k) for k in self.env_keys):
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as exc:
            raise ProviderUnavailable(
                "не установлен SDK: pip install 'agentos[anthropic]'", provider=self.name
            ) from exc
        if not any(os.environ.get(k) for k in self.env_keys):
            raise ProviderUnavailable("нет ANTHROPIC_API_KEY", provider=self.name)
        self._client = anthropic.Anthropic()
        return self._client

    # ------------------------------------------------------------ конвертация
    @staticmethod
    def _to_native_messages(messages: list[Message]) -> list[dict[str, Any]]:
        native: list[dict[str, Any]] = []
        for msg in messages:
            role = "assistant" if msg.role == "assistant" else "user"
            if isinstance(msg.content, str):
                native.append({"role": role, "content": msg.content})
                continue
            blocks: list[dict[str, Any]] = []
            for block in msg.content:
                if block.type == "text" and block.text:
                    blocks.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": block.tool_call_id,
                            "name": block.tool_name,
                            "input": block.arguments,
                        }
                    )
                elif block.type == "tool_result":
                    blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.tool_call_id,
                            "content": block.text,
                            "is_error": block.is_error,
                        }
                    )
            if blocks:
                native.append({"role": role, "content": blocks})
        return native

    @staticmethod
    def _to_native_tools(tools: list[ToolSpec] | None) -> list[dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
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
            "max_tokens": max_tokens,
            "messages": self._to_native_messages(messages),
        }
        if system:
            # cache_control на стабильном префиксе — основной рычаг экономии
            # при веерном запуске субагентов с общим системным промптом.
            kwargs["system"] = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        if tools:
            kwargs["tools"] = self._to_native_tools(tools)
        if stop:
            kwargs["stop_sequences"] = stop
        if self._supports_thinking(model):
            kwargs["thinking"] = {"type": "adaptive"}

        try:
            if max_tokens > _STREAM_ABOVE_TOKENS:
                with client.messages.stream(**kwargs) as stream:
                    response = stream.get_final_message()
            else:
                response = client.messages.create(**kwargs)
        except Exception as exc:  # адаптер обязан вернуть нормализованную ошибку
            raise self._normalize(exc, model) from exc

        return self._to_completion(response, model)

    @staticmethod
    def _supports_thinking(model: str) -> bool:
        """Адаптивное мышление есть у opus/sonnet текущих поколений."""
        return model.startswith(("claude-opus", "claude-sonnet-5", "claude-fable"))

    def _to_completion(self, response: Any, model: str) -> Completion:
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in getattr(response, "content", []) or []:
            btype = getattr(block, "type", "")
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input)))
        usage_obj = getattr(response, "usage", None)
        usage = Usage(
            tokens_in=int(getattr(usage_obj, "input_tokens", 0) or 0),
            tokens_out=int(getattr(usage_obj, "output_tokens", 0) or 0),
            cached_in=int(getattr(usage_obj, "cache_read_input_tokens", 0) or 0),
        )
        return Completion(
            text="\n".join(text_parts).strip(),
            tool_calls=calls,
            usage=usage,
            stop_reason=str(getattr(response, "stop_reason", "") or ""),
            model=str(getattr(response, "model", model)),
            provider=self.name,
            raw=response,
        )

    # ------------------------------------------------------------- нормализация
    def _normalize(self, exc: Exception, model: str) -> Exception:
        try:
            import anthropic
        except ImportError:
            return TransientProviderError(str(exc), provider=self.name, model=model)

        message = str(getattr(exc, "message", "") or exc)
        lowered = message.lower()

        if isinstance(exc, anthropic.RateLimitError):
            retry_after = _retry_after_of(exc)
            # 429 бывает и «кончились деньги/окно», и «слишком часто».
            if any(hint in lowered for hint in _QUOTA_HINTS):
                return QuotaExhausted(
                    message, reset_at=time.time() + retry_after, provider=self.name, model=model
                )
            return RateLimited(
                message, retry_after_s=retry_after, provider=self.name, model=model
            )
        if isinstance(exc, anthropic.BadRequestError):
            if any(hint in lowered for hint in _OVERFLOW_HINTS):
                return ContextOverflow(message, provider=self.name, model=model)
            if any(hint in lowered for hint in _QUOTA_HINTS):
                return QuotaExhausted(message, provider=self.name, model=model)
            return TransientProviderError(message, provider=self.name, model=model)
        if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            return ProviderUnavailable(message, provider=self.name, model=model)
        if isinstance(exc, anthropic.APIStatusError):
            status = int(getattr(exc, "status_code", 0) or 0)
            if status == 402 or any(hint in lowered for hint in _QUOTA_HINTS):
                return QuotaExhausted(message, provider=self.name, model=model)
            return TransientProviderError(message, provider=self.name, model=model)
        return TransientProviderError(message, provider=self.name, model=model)


def _retry_after_of(exc: Any, default: float = 60.0) -> float:
    """Достать retry-after из ответа; если его нет — разумный дефолт."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        raw = headers.get("retry-after") or headers.get("Retry-After")
        if raw:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:s|sec|seconds)", str(exc))
    return float(match.group(1)) if match else default
