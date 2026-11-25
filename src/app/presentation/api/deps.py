"""Dependency wiring for the FastAPI application.

The composition root builds providers and the use case once, and hands them to
routers through FastAPI dependencies. This is the only place that knows the concrete
classes; routers depend on ports.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.application.use_cases.analyze_load import AnalyzeLoadUseCase
from app.config import Settings
from app.domain.entities.vehicle import VehicleProfile
from app.domain.rules.recommendation import ProfitThresholds
from app.domain.value_objects.money import Money, RatePerMile
from app.infrastructure.ai.gemini import GeminiVisionProvider
from app.infrastructure.market.freight_datawatch import (
    FreightDataWatchClient,
    FreightDataWatchMarketProvider,
)
from app.infrastructure.persistence.sqlite import SqliteAnalysisRepository


class _UtcClock:
    """A clock that returns the current UTC time."""

    def now(self) -> datetime:
        return datetime.now(UTC)


def build_use_case(settings: Settings) -> AnalyzeLoadUseCase:
    """Build the fully wired use case. Callers own the provider lifetimes."""
    vision = GeminiVisionProvider(settings)
    market_client = FreightDataWatchClient(settings)
    market = FreightDataWatchMarketProvider(market_client)
    # Routing and weather are not implemented yet; the use case degrades gracefully.
    repository = SqliteAnalysisRepository(settings.DATABASE_URL)
    return AnalyzeLoadUseCase(
        vision=vision,
        market=market,
        routing=None,
        clock=_UtcClock(),
        repository=repository,
    )


class DefaultLoadConfig:
    """A sensible default configuration for the API surface.

    In production this would be replaced by a per-user vehicle profile and per-user
    thresholds. For now it uses the minimal vehicle and a neutral threshold set.
    """

    thresholds: ProfitThresholds = ProfitThresholds(
        minimum_net_profit=Money(amount=Decimal(0)),
        minimum_net_rpm=RatePerMile(amount=Decimal(0)),
    )
    vehicle: VehicleProfile | None = None
