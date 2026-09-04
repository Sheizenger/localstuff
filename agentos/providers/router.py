"""Маршрутизация запросов к моделям.

Роутер отвечает на один вопрос: «какой моделью выполнить задачу тира T
прямо сейчас». Учитывает: настроен ли провайдер, не выбрана ли его квота,
хватает ли бюджета, и не должен ли критик взять другого провайдера.

Принцип, который здесь важнее скорости: mock никогда не подменяет молча
настоящего провайдера. Если ключи есть, но все лимиты выбраны — роутер
честно бросает QuotaExhausted, и задача уходит ждать сброса, а не получает
выдуманный результат.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from ..config import Config, ModelSpec
from ..errors import ProviderUnavailable, QuotaExhausted
from ..telemetry.quota import QuotaTracker
from .base import Provider
from .registry import get_provider

#: Понижение тира, когда в нужном ничего не доступно.
TIER_DEGRADE: dict[str, str] = {
    "reasoning": "large",
    "large": "small",
    "small": "nano",
    "nano": "",
}


@dataclass(frozen=True)
class Route:
    """Выбранная пара «адаптер + модель»."""

    provider: Provider
    spec: ModelSpec
    degraded_from: str = ""

    @property
    def name(self) -> str:
        return f"{self.spec.provider}/{self.spec.id}"


class Router:
    def __init__(self, config: Config, quota: QuotaTracker) -> None:
        self.config = config
        self.quota = quota

    # ------------------------------------------------------------------ выбор
    def pick(
        self,
        tier: str,
        *,
        exclude_providers: tuple[str, ...] = (),
        avoid_providers: tuple[str, ...] = (),
    ) -> Route:
        """Выбрать модель для тира.

        exclude_providers — жёсткий запрет (например, «не тот, кто писал код»).
        avoid_providers   — мягкое предпочтение: берём другого, если он есть.
        """
        allow_mock = self._mock_allowed()
        blocked_resets: list[float] = []
        current = tier
        degraded_from = ""

        while current:
            candidates = [
                spec
                for spec in self.config.models_for_tier(current)
                if spec.provider not in exclude_providers
                and (spec.provider != "mock" or allow_mock)
            ]
            # Мягкое предпочтение: сначала те, кого не просили избегать.
            ordered = [c for c in candidates if c.provider not in avoid_providers]
            ordered += [c for c in candidates if c.provider in avoid_providers]

            for spec in ordered:
                provider = get_provider(spec.provider)
                if not provider.available():
                    continue
                state = self.quota.get(spec.provider)
                if not state.available:
                    if state.reset_at:
                        blocked_resets.append(state.reset_at)
                    continue
                return Route(provider=provider, spec=spec, degraded_from=degraded_from)

            degraded_from = degraded_from or current
            current = TIER_DEGRADE.get(current, "")

        if blocked_resets:
            raise QuotaExhausted(
                "все подходящие провайдеры ждут сброса лимитов",
                reset_at=min(blocked_resets),
            )
        raise ProviderUnavailable(
            f"нет доступной модели для тира '{tier}': проверь ключи и config/models.yaml"
        )

    def try_pick(self, tier: str, **kwargs) -> Route | None:
        try:
            return self.pick(tier, **kwargs)
        except (QuotaExhausted, ProviderUnavailable):
            return None

    # ------------------------------------------------------------ вспомогательное
    @staticmethod
    def _mock_allowed() -> bool:
        """Mock включается только явным AGENTOS_ALLOW_MOCK=1 — тесты и evals.

        Раньше он разрешался при отсутствии настоящих провайдеров, и в
        native-режиме выдуманный план выглядел бы как настоящий. Теперь без
        ключей маршрут просто не находится: intake и planner честно уходят
        на детерминированные заготовки, а рассуждает агент-хост.
        """
        return os.environ.get("AGENTOS_ALLOW_MOCK") == "1"

    def chain_for(self, tier: str) -> list[str]:
        """Читаемая цепочка запасных вариантов — для doctor и диагностики."""
        out: list[str] = []
        current = tier
        while current:
            out += [f"{s.provider}/{s.id}" for s in self.config.models_for_tier(current)]
            current = TIER_DEGRADE.get(current, "")
        return out

    def critic_route(self, tier: str, producer_provider: str) -> Route:
        """Модель для критика: по возможности другого провайдера, чем автор.

        Кросс-провайдерная проверка ловит то, что модель одного семейства
        склонна повторять за собой.
        """
        cross = bool(self.config.get("self_check.cross_provider", True))
        if not cross or not producer_provider:
            return self.pick(tier)
        try:
            return self.pick(tier, exclude_providers=(producer_provider,))
        except (QuotaExhausted, ProviderUnavailable):
            # Другого провайдера нет — лучше проверить тем же, чем не проверять.
            return self.pick(tier)
