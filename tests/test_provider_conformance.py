"""Контрактный набор, одинаковый для всех адаптеров.

Проверяется то, что делает провайдеров взаимозаменяемыми: конвертация
сообщений и инструментов в родной формат, разбор ответа, подсчёт usage и —
главное — нормализация ошибок. Если адаптер вернёт «просто исключение»
вместо QuotaExhausted, авто-resume перестанет работать молча.

Сеть не нужна: SDK подменяются заглушками. Тесты с реальными ключами
помечены `live` и по умолчанию не запускаются.
"""

from __future__ import annotations

import types

import pytest

from agentos.errors import ProviderUnavailable, QuotaExhausted, RateLimited
from agentos.providers.anthropic import AnthropicProvider
from agentos.providers.base import ContentBlock, Message, Provider, ToolSpec
from agentos.providers.google import GoogleProvider
from agentos.providers.mock import MockProvider
from agentos.providers.openai import OpenAIProvider

ALL_ADAPTERS = [AnthropicProvider, OpenAIProvider, GoogleProvider, MockProvider]

TOOL = ToolSpec(
    name="fs_read",
    description="прочитать файл",
    input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
)
CONVERSATION = [
    Message.user("прочитай README"),
    Message(
        role="assistant",
        content=[
            ContentBlock(
                type="tool_use", tool_call_id="c1", tool_name="fs_read",
                arguments={"path": "README.md"},
            )
        ],
    ),
    Message(role="user", content=[ContentBlock.of_tool_result("c1", "содержимое")]),
]


@pytest.mark.parametrize("adapter_cls", ALL_ADAPTERS)
def test_adapter_declares_the_contract(adapter_cls):
    adapter = adapter_cls()
    assert isinstance(adapter, Provider)
    assert adapter.name
    assert isinstance(adapter.available(), bool)
    if not adapter.available():
        assert adapter.missing_reason(), "недоступность должна объясняться человеку"


@pytest.mark.parametrize("adapter_cls", [AnthropicProvider, OpenAIProvider, GoogleProvider])
def test_unavailable_adapter_fails_loudly_not_silently(adapter_cls):
    """Без ключа адаптер обязан сказать это, а не вернуть пустой ответ."""
    adapter = adapter_cls()
    if adapter.available():
        pytest.skip("адаптер настроен, проверяется live-тестами")
    with pytest.raises(ProviderUnavailable):
        adapter.complete(model="любая", messages=[Message.user("привет")])


def test_anthropic_message_conversion():
    native = AnthropicProvider._to_native_messages(CONVERSATION)
    assert native[0] == {"role": "user", "content": "прочитай README"}
    assert native[1]["content"][0]["type"] == "tool_use"
    assert native[1]["content"][0]["input"] == {"path": "README.md"}
    assert native[2]["content"][0]["tool_use_id"] == "c1"

    tools = AnthropicProvider._to_native_tools([TOOL])
    assert tools[0]["input_schema"]["properties"]["path"]["type"] == "string"


def test_openai_message_conversion():
    native = OpenAIProvider._to_native_messages(CONVERSATION, system="ты помощник")
    assert native[0]["role"] == "system"
    # Результат инструмента у OpenAI — отдельное сообщение роли tool.
    assert any(m["role"] == "tool" and m["tool_call_id"] == "c1" for m in native)
    assert any(m.get("tool_calls") for m in native)

    tools = OpenAIProvider._to_native_tools([TOOL])
    assert tools[0]["function"]["name"] == "fs_read"


def test_google_message_conversion():
    contents = GoogleProvider._to_contents(CONVERSATION)
    assert contents[0]["role"] == "user"
    assert contents[1]["role"] == "model", "у Gemini ассистент называется model"
    assert contents[1]["parts"][0]["function_call"]["name"] == "fs_read"

    tools = GoogleProvider._to_native_tools([TOOL])
    assert tools[0]["function_declarations"][0]["name"] == "fs_read"


def test_anthropic_normalizes_quota_and_rate_limit(monkeypatch):
    """429 бывает и «слишком часто», и «кончились деньги» — это разные вещи."""
    fake_sdk = types.SimpleNamespace(
        RateLimitError=type("RateLimitError", (Exception,), {}),
        BadRequestError=type("BadRequestError", (Exception,), {}),
        AuthenticationError=type("AuthenticationError", (Exception,), {}),
        PermissionDeniedError=type("PermissionDeniedError", (Exception,), {}),
        APIStatusError=type("APIStatusError", (Exception,), {}),
    )
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_sdk)
    adapter = AnthropicProvider()

    quota = adapter._normalize(
        fake_sdk.RateLimitError("your credit balance is too low"), "claude-opus-5"
    )
    assert isinstance(quota, QuotaExhausted)
    assert quota.reset_at is not None, "система должна знать, когда пробовать снова"

    throttled = adapter._normalize(fake_sdk.RateLimitError("too many requests"), "claude-opus-5")
    assert isinstance(throttled, RateLimited)
    assert throttled.retry_after_s > 0

    overflow = adapter._normalize(
        fake_sdk.BadRequestError("prompt is too long for this model"), "claude-opus-5"
    )
    assert type(overflow).__name__ == "ContextOverflow"


def test_google_normalizes_resource_exhausted():
    error = GoogleProvider()._normalize(
        Exception("429 RESOURCE_EXHAUSTED: quota exceeded"), "gemini-2.5-pro"
    )
    assert isinstance(error, QuotaExhausted)


def test_mock_usage_is_counted():
    completion = MockProvider().complete(
        model="mock-small", messages=[Message.user("привет" * 100)], max_tokens=100
    )
    assert completion.usage.tokens_in > 0
    assert completion.usage.total == completion.usage.tokens_in + completion.usage.tokens_out
    assert completion.provider == "mock"


@pytest.mark.live
@pytest.mark.parametrize("adapter_cls", [AnthropicProvider, OpenAIProvider, GoogleProvider])
def test_live_completion(adapter_cls):
    """Настоящий вызов. Запускается только при наличии ключа: pytest -m live."""
    adapter = adapter_cls()
    if not adapter.available():
        pytest.skip(f"{adapter.name}: нет ключа")
    from agentos.config import Config

    config = Config.load()
    model = next(m for m in config.models if m.provider == adapter.name and m.tier == "nano")
    completion = adapter.complete(
        model=model.id, messages=[Message.user("ответь одним словом: работает")], max_tokens=64
    )
    assert completion.text
    assert completion.usage.tokens_in > 0
