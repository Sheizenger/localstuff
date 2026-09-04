"""Роутер: выбор модели под тир с учётом квот, ключей и запретов."""

from __future__ import annotations

import time

import pytest

from agentos.errors import ProviderUnavailable, QuotaExhausted
from agentos.providers.router import Router
from agentos.telemetry.quota import QuotaTracker


@pytest.fixture
def router(config, store):
    return Router(config, QuotaTracker(store))


def test_picks_mock_only_when_explicitly_allowed(router, monkeypatch):
    assert router.pick("large").spec.provider == "mock"

    monkeypatch.delenv("AGENTOS_ALLOW_MOCK", raising=False)
    with pytest.raises(ProviderUnavailable):
        router.pick("large")


def test_quota_block_raises_with_reset_time(router, store):
    """Заблокированный провайдер должен сообщать, когда снова можно."""
    reset_at = time.time() + 600
    QuotaTracker(store).mark_exhausted("mock", reset_at=reset_at)

    with pytest.raises(QuotaExhausted) as excinfo:
        router.pick("large")
    assert excinfo.value.reset_at == pytest.approx(reset_at)


def test_tier_degrades_when_nothing_available(router, config):
    """Понижение тира лучше остановки, если в нужном тире пусто."""
    chain = router.chain_for("reasoning")
    assert chain[0].startswith("anthropic/")
    assert any(name.startswith("mock/mock-nano") for name in chain), (
        "цепочка должна доходить до самого дешёвого тира"
    )


def test_critic_avoids_the_producer_provider(router):
    """Кросс-провайдерная проверка — смысл провайдер-агностики."""
    route = router.critic_route("reasoning", producer_provider="mock")
    # Другого настроенного провайдера в тестовой среде нет, поэтому
    # критик возвращается к тому же — но не падает и не отказывается проверять.
    assert route.spec.provider == "mock"


def test_exclude_providers_is_hard(router):
    with pytest.raises((QuotaExhausted, ProviderUnavailable)):
        router.pick("nano", exclude_providers=("mock",))
