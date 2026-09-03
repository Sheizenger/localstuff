"""Единая иерархия ошибок AgentOS.

Всё, что может пойти не так у провайдера, приводится к этим типам —
оркестратор принимает решения по ним, а не по строкам сообщений.
"""

from __future__ import annotations


class AgentOSError(Exception):
    """Базовая ошибка."""


class ConfigError(AgentOSError):
    """Конфиг отсутствует, невалиден или противоречив."""


class PolicyDenied(AgentOSError):
    """Действие запрещено политикой безопасности."""


class ApprovalRequired(AgentOSError):
    """Нужно подтверждение человека. Задача уходит в BLOCKED_APPROVAL."""

    def __init__(self, action: str, detail: str = "") -> None:
        super().__init__(f"нужно подтверждение: {action}. {detail}".strip())
        self.action = action
        self.detail = detail


class CapabilityMissing(AgentOSError):
    """Не хватает возможности (навык, MCP-сервер, доступ, секрет)."""

    def __init__(self, kind: str, name: str, how_to_fix: str = "") -> None:
        super().__init__(f"не хватает {kind}: {name}. {how_to_fix}".strip())
        self.kind = kind
        self.name = name
        self.how_to_fix = how_to_fix


class ProviderError(AgentOSError):
    """Базовая ошибка провайдера."""

    def __init__(self, message: str, provider: str = "", model: str = "") -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model


class ProviderUnavailable(ProviderError):
    """Провайдер не настроен: нет ключа, не установлен SDK."""


class TransientProviderError(ProviderError):
    """Временный сбой (5xx, обрыв связи). Имеет смысл повторить."""


class RateLimited(ProviderError):
    """Упёрлись в rate limit. Ждать retry_after секунд."""

    def __init__(self, message: str, retry_after_s: float = 60.0, **kw) -> None:
        super().__init__(message, **kw)
        self.retry_after_s = retry_after_s


class QuotaExhausted(ProviderError):
    """Лимит токенов/бюджета исчерпан до reset_at (unix ts).

    Ключевая ошибка для автономности: задача уходит в BLOCKED_QUOTA
    и продолжится сама, когда лимит сбросится.
    """

    def __init__(self, message: str, reset_at: float | None = None, **kw) -> None:
        super().__init__(message, **kw)
        self.reset_at = reset_at


class ContextOverflow(ProviderError):
    """Запрос не влезает в контекстное окно — нужна компакция."""


class BudgetExceeded(AgentOSError):
    """Исчерпан бюджет миссии, заданный человеком."""


class InvalidTransition(AgentOSError):
    """Недопустимый переход состояния — признак бага, а не внешнего сбоя."""
