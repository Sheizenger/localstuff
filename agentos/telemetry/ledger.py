"""Леджер расхода — единственный источник правды по токенам и деньгам.

Каждая запись имеет dedupe_key. Это то, что делает resume честным: после
краша повторно записанный вызов не удваивает счётчик, потому что ключ уже занят.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..config import Config
from ..errors import BudgetExceeded
from ..memory.store import Store


@dataclass(frozen=True)
class Spend:
    """Сколько потрачено и сколько осталось."""

    tokens: int
    usd: float
    budget_tokens: int
    budget_usd: float

    @property
    def tokens_left(self) -> int:
        return max(0, self.budget_tokens - self.tokens) if self.budget_tokens else 0

    @property
    def usd_left(self) -> float:
        return max(0.0, self.budget_usd - self.usd) if self.budget_usd else 0.0

    @property
    def exhausted(self) -> bool:
        """Бюджет исчерпан хотя бы по одному измерению."""
        if self.budget_tokens and self.tokens >= self.budget_tokens:
            return True
        return bool(self.budget_usd) and self.usd >= self.budget_usd

    @property
    def fraction_used(self) -> float:
        parts = []
        if self.budget_tokens:
            parts.append(self.tokens / self.budget_tokens)
        if self.budget_usd:
            parts.append(self.usd / self.budget_usd)
        return max(parts) if parts else 0.0


class Ledger:
    """Запись и чтение расхода."""

    def __init__(self, store: Store, config: Config) -> None:
        self.store = store
        self.config = config

    # ------------------------------------------------------------------ write
    def record(
        self,
        *,
        provider: str,
        model: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cached_in: int = 0,
        mission_id: str = "",
        task_id: str = "",
        kind: str = "completion",
        dedupe_key: str | None = None,
        usd: float | None = None,
    ) -> float:
        """Записать расход. Возвращает стоимость записи в долларах.

        Если dedupe_key уже встречался, запись игнорируется и возвращается 0 —
        повторный проход после краша не должен удваивать счётчики.
        """
        cost = usd if usd is not None else self._price(provider, model, tokens_in, tokens_out)
        with self.store.tx() as conn:
            if dedupe_key:
                exists = conn.execute(
                    "SELECT 1 FROM usage WHERE dedupe_key=?", (dedupe_key,)
                ).fetchone()
                if exists:
                    return 0.0
            conn.execute(
                "INSERT INTO usage(ts, mission_id, task_id, provider, model, tokens_in,"
                " tokens_out, cached_in, usd, kind, dedupe_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    time.time(),
                    mission_id,
                    task_id,
                    provider,
                    model,
                    tokens_in,
                    tokens_out,
                    cached_in,
                    cost,
                    kind,
                    dedupe_key,
                ),
            )
            total = tokens_in + tokens_out
            if task_id:
                conn.execute(
                    "UPDATE tasks SET used_tokens=used_tokens+?, used_usd=used_usd+?,"
                    " updated_at=? WHERE id=?",
                    (total, cost, time.time(), task_id),
                )
            if mission_id:
                conn.execute(
                    "UPDATE missions SET used_tokens=used_tokens+?, used_usd=used_usd+?,"
                    " updated_at=? WHERE id=?",
                    (total, cost, time.time(), mission_id),
                )
        return cost

    def _price(self, provider: str, model: str, tokens_in: int, tokens_out: int) -> float:
        for spec in self.config.models:
            if spec.provider == provider and spec.id == model:
                return spec.cost_usd(tokens_in, tokens_out)
        return 0.0

    # ------------------------------------------------------------------- read
    def mission_spend(self, mission_id: str) -> Spend:
        row = self.store.one(
            "SELECT used_tokens, used_usd, budget_tokens, budget_usd FROM missions WHERE id=?",
            (mission_id,),
        )
        if not row:
            return Spend(0, 0.0, 0, 0.0)
        return Spend(
            tokens=int(row["used_tokens"]),
            usd=float(row["used_usd"]),
            budget_tokens=int(row["budget_tokens"]),
            budget_usd=float(row["budget_usd"]),
        )

    def check_budget(self, mission_id: str) -> Spend:
        """Бросить BudgetExceeded, если бюджет миссии исчерпан."""
        spend = self.mission_spend(mission_id)
        if spend.exhausted:
            raise BudgetExceeded(
                f"бюджет миссии исчерпан: {spend.tokens} токенов / ${spend.usd:.2f}"
            )
        return spend

    def allocate(self, mission_id: str, est_tokens: int) -> int:
        """Сколько токенов реально выделить задаче с оценкой est_tokens.

        Часть бюджета всегда держится в резерве под критика и доработки —
        иначе проверка результата упирается в пустой кошелёк.
        """
        spend = self.mission_spend(mission_id)
        if not spend.budget_tokens:
            return est_tokens
        reserve = float(self.config.get("budget.reserve_fraction", 0.25))
        spendable = max(0, int(spend.tokens_left * (1.0 - reserve)))
        return max(0, min(est_tokens, spendable)) if est_tokens else spendable

    def by_provider(self, mission_id: str = "") -> list[dict[str, Any]]:
        return self.store.query(
            "SELECT provider, model, SUM(tokens_in) AS tin, SUM(tokens_out) AS tout,"
            " SUM(usd) AS usd, COUNT(*) AS calls FROM usage"
            " WHERE (?='' OR mission_id=?) GROUP BY provider, model ORDER BY usd DESC",
            (mission_id, mission_id),
        )

    def totals(self) -> dict[str, Any]:
        row = self.store.one(
            "SELECT COALESCE(SUM(tokens_in+tokens_out),0) AS tokens,"
            " COALESCE(SUM(usd),0) AS usd, COUNT(*) AS calls FROM usage"
        )
        return row or {"tokens": 0, "usd": 0.0, "calls": 0}
