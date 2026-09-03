"""Реестр адаптеров: имя провайдера -> объект-адаптер (синглтон на процесс)."""

from __future__ import annotations

from typing import Any

from ..errors import ProviderUnavailable
from .base import Provider

_BUILDERS: dict[str, Any] = {}
_CACHE: dict[str, Provider] = {}


def _builders() -> dict[str, Any]:
    """Ленивая регистрация: SDK провайдеров импортируются только при вызове."""
    if _BUILDERS:
        return _BUILDERS
    from .anthropic import AnthropicProvider
    from .google import GoogleProvider
    from .mock import MockProvider
    from .openai import OpenAIProvider

    _BUILDERS.update(
        {
            "anthropic": AnthropicProvider,
            "openai": OpenAIProvider,
            "google": GoogleProvider,
            "mock": MockProvider,
        }
    )
    return _BUILDERS


def get_provider(name: str) -> Provider:
    if name in _CACHE:
        return _CACHE[name]
    builder = _builders().get(name)
    if builder is None:
        known = ", ".join(sorted(_builders()))
        raise ProviderUnavailable(f"неизвестный провайдер: {name}. Известные: {known}")
    provider = builder()
    _CACHE[name] = provider
    return provider


def list_providers() -> list[Provider]:
    return [get_provider(name) for name in sorted(_builders())]


def availability() -> dict[str, bool]:
    """Карта «провайдер -> готов ли работать». Используется в doctor и роутере."""
    return {p.name: p.available() for p in list_providers()}


def real_providers_configured() -> bool:
    """Есть ли хоть один настоящий (не mock) провайдер с ключом и SDK."""
    return any(name != "mock" and ok for name, ok in availability().items())


def reset_cache() -> None:
    """Сбросить синглтоны — нужно тестам, меняющим окружение."""
    _CACHE.clear()
