"""Учёт расхода и лимитов.

Двойной учёт после краша и «зависшая навсегда» квота — два способа
незаметно сломать автономность, поэтому они проверяются явно.
"""

from __future__ import annotations

import time

import pytest

from agentos.errors import BudgetExceeded
from agentos.telemetry.ledger import Ledger
from agentos.telemetry.quota import STATE_EXHAUSTED, QuotaTracker


@pytest.fixture
def ledger(store, config):
    return Ledger(store, config)


def test_cost_is_computed_from_catalog(ledger, sm):
    mission = sm.create_mission("цель", budget_tokens=100_000, budget_usd=10.0)
    cost = ledger.record(
        provider="anthropic",
        model="claude-opus-5",
        tokens_in=1_000_000,
        tokens_out=0,
        mission_id=mission,
    )
    assert cost == pytest.approx(5.0), "цена входных токенов берётся из config/models.yaml"


def test_dedupe_key_prevents_double_counting(ledger, sm):
    """После краша тот же вызов может записаться повторно — и не должен."""
    mission = sm.create_mission("цель", budget_tokens=100_000)
    task = sm.add_task(mission, title="A", role="coder")

    first = ledger.record(
        provider="anthropic", model="claude-opus-5", tokens_in=1000, tokens_out=500,
        mission_id=mission, task_id=task, dedupe_key="call-1",
    )
    second = ledger.record(
        provider="anthropic", model="claude-opus-5", tokens_in=1000, tokens_out=500,
        mission_id=mission, task_id=task, dedupe_key="call-1",
    )

    assert first > 0
    assert second == 0.0
    assert ledger.mission_spend(mission).tokens == 1500


def test_budget_exhaustion_is_detected(ledger, sm):
    mission = sm.create_mission("цель", budget_tokens=1000)
    ledger.record(provider="mock", model="mock-small", tokens_in=600, tokens_out=500,
                  mission_id=mission)

    spend = ledger.mission_spend(mission)
    assert spend.exhausted
    with pytest.raises(BudgetExceeded):
        ledger.check_budget(mission)


def test_allocation_keeps_a_reserve(ledger, sm, config):
    """Без резерва критику не на что проверить результат."""
    mission = sm.create_mission("цель", budget_tokens=100_000)
    allocated = ledger.allocate(mission, est_tokens=10**9)
    reserve = float(config.get("budget.reserve_fraction", 0.25))

    assert allocated == pytest.approx(100_000 * (1 - reserve), rel=0.01)
    assert allocated < 100_000


def test_quota_blocks_until_reset_then_clears(store):
    quota = QuotaTracker(store, default_cooldown_s=60)
    state = quota.mark_exhausted("openai", reset_at=time.time() + 300, error="429")

    assert state.state == STATE_EXHAUSTED
    assert not quota.available("openai")
    assert 0 < state.wait_s <= 300
    assert quota.next_reset() is not None

    quota.mark_exhausted("openai", reset_at=time.time() - 1)
    assert quota.sweep() == ["openai"]
    assert quota.available("openai")


def test_rate_limit_uses_retry_after(store):
    quota = QuotaTracker(store)
    state = quota.mark_rate_limited("anthropic", retry_after_s=30)
    assert 0 < state.wait_s <= 30
