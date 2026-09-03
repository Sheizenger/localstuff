"""Состояние лимитов провайдеров.

Здесь живёт ответ на вопрос «можно ли сейчас звонить этому провайдеру».
Роутер спрашивает перед выбором модели, супервизор — чтобы понять,
когда сама собой продолжится заблокированная работа.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..memory.store import Store

STATE_OK = "ok"
STATE_LIMITED = "limited"        # временный rate limit, ждём секунды-минуты
STATE_EXHAUSTED = "exhausted"    # лимит окна выбран, ждём сброса


@dataclass(frozen=True)
class QuotaState:
    provider: str
    state: str
    reset_at: float | None
    last_error: str

    @property
    def available(self) -> bool:
        if self.state == STATE_OK:
            return True
        return self.reset_at is not None and self.reset_at <= time.time()

    @property
    def wait_s(self) -> float:
        if self.available or self.reset_at is None:
            return 0.0
        return max(0.0, self.reset_at - time.time())


class QuotaTracker:
    def __init__(self, store: Store, default_cooldown_s: float = 900.0) -> None:
        self.store = store
        self.default_cooldown_s = default_cooldown_s

    def get(self, provider: str) -> QuotaState:
        row = self.store.one("SELECT * FROM quota WHERE provider=?", (provider,))
        if not row:
            return QuotaState(provider, STATE_OK, None, "")
        return QuotaState(provider, row["state"], row["reset_at"], row["last_error"])

    def available(self, provider: str) -> bool:
        return self.get(provider).available

    def mark(
        self,
        provider: str,
        state: str,
        *,
        reset_at: float | None = None,
        error: str = "",
    ) -> QuotaState:
        moment = reset_at if reset_at is not None else time.time() + self.default_cooldown_s
        if state == STATE_OK:
            moment = None  # type: ignore[assignment]
        with self.store.tx() as conn:
            conn.execute(
                "INSERT INTO quota(provider, state, reset_at, last_error, updated_at)"
                " VALUES(?,?,?,?,?) ON CONFLICT(provider) DO UPDATE SET"
                " state=excluded.state, reset_at=excluded.reset_at,"
                " last_error=excluded.last_error, updated_at=excluded.updated_at",
                (provider, state, moment, error[:500], time.time()),
            )
        return self.get(provider)

    def mark_rate_limited(self, provider: str, retry_after_s: float, error: str = "") -> QuotaState:
        return self.mark(
            provider, STATE_LIMITED, reset_at=time.time() + max(1.0, retry_after_s), error=error
        )

    def mark_exhausted(
        self, provider: str, reset_at: float | None = None, error: str = ""
    ) -> QuotaState:
        return self.mark(provider, STATE_EXHAUSTED, reset_at=reset_at, error=error)

    def clear(self, provider: str) -> QuotaState:
        return self.mark(provider, STATE_OK)

    def sweep(self) -> list[str]:
        """Снять блокировки, у которых вышел срок. Возвращает список провайдеров."""
        now = time.time()
        rows = self.store.query(
            "SELECT provider FROM quota WHERE state != ? AND reset_at IS NOT NULL"
            " AND reset_at <= ?",
            (STATE_OK, now),
        )
        cleared = [r["provider"] for r in rows]
        for provider in cleared:
            self.clear(provider)
        return cleared

    def all(self) -> list[dict[str, Any]]:
        return self.store.query("SELECT * FROM quota ORDER BY provider")

    def next_reset(self) -> float | None:
        value = self.store.scalar(
            "SELECT MIN(reset_at) AS t FROM quota WHERE state != ? AND reset_at IS NOT NULL",
            (STATE_OK,),
        )
        return float(value) if value is not None else None
