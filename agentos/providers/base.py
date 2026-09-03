"""Единый контракт провайдера.

Смысл слоя: оркестратор, память и критик не знают, чей API под ними.
Каждый адаптер обязан привести к этим типам и к ошибкам из agentos.errors —
особенно QuotaExhausted, потому что на ней держится авто-resume.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ContentBlock:
    """Кусок сообщения. type: text | tool_use | tool_result."""

    type: str
    text: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False

    @classmethod
    def of_text(cls, text: str) -> ContentBlock:
        return cls(type="text", text=text)

    @classmethod
    def of_tool_result(cls, call_id: str, text: str, is_error: bool = False) -> ContentBlock:
        return cls(type="tool_result", tool_call_id=call_id, text=text, is_error=is_error)


@dataclass
class Message:
    """Сообщение диалога, независимое от формата провайдера."""

    role: Role
    content: str | list[ContentBlock]

    def blocks(self) -> list[ContentBlock]:
        if isinstance(self.content, str):
            return [ContentBlock.of_text(self.content)]
        return self.content

    def as_text(self) -> str:
        return "\n".join(b.text for b in self.blocks() if b.type == "text" and b.text)

    @classmethod
    def user(cls, text: str) -> Message:
        return cls(role="user", content=text)

    @classmethod
    def assistant(cls, text: str) -> Message:
        return cls(role="assistant", content=text)


@dataclass
class ToolSpec:
    """Описание инструмента в формате JSON Schema."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})


@dataclass
class ToolCall:
    """Запрос модели на вызов инструмента."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class Usage:
    """Расход одного вызова. cached_in учитывается отдельно: он дешевле."""

    tokens_in: int = 0
    tokens_out: int = 0
    cached_in: int = 0

    @property
    def total(self) -> int:
        return self.tokens_in + self.tokens_out

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.tokens_in + other.tokens_in,
            self.tokens_out + other.tokens_out,
            self.cached_in + other.cached_in,
        )


@dataclass
class Completion:
    """Ответ модели, приведённый к общему виду."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    stop_reason: str = ""
    model: str = ""
    provider: str = ""
    raw: Any = None

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)

    def json(self, default: Any = None) -> Any:
        """Разобрать ответ как JSON, терпимо к обёртке в ```-блок.

        Модели регулярно оборачивают JSON в markdown-блок; ронять из-за этого
        целую задачу — дороже, чем аккуратно снять обёртку.
        """
        text = self.text.strip()
        if text.startswith("```"):
            lines = [ln for ln in text.splitlines() if not ln.strip().startswith("```")]
            text = "\n".join(lines).strip()
        if not text:
            return default
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    return default
            return default


class Provider(ABC):
    """Базовый адаптер. Реализация обязана нормализовать ошибки."""

    #: Имя провайдера, совпадает с полем provider в config/models.yaml.
    name: str = ""
    #: Переменные окружения, любой из которых достаточно для работы.
    env_keys: tuple[str, ...] = ()

    @abstractmethod
    def available(self) -> bool:
        """Готов ли адаптер к работе: есть ключ и установлен SDK."""

    @abstractmethod
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
        """Один вызов модели."""

    def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        """Эмбеддинги. По умолчанию — не поддерживается."""
        raise NotImplementedError(f"{self.name}: эмбеддинги не поддерживаются")

    # --------------------------------------------------------------- helpers
    def missing_reason(self) -> str:
        """Почему адаптер недоступен — текст для `agentctl doctor`."""
        if self.available():
            return ""
        keys = " или ".join(self.env_keys) or "—"
        return f"нет ключа ({keys}) либо не установлен SDK провайдера {self.name}"
