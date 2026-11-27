"""Dependency wiring for the FastAPI application.

The composition root builds providers and the use case once, and hands them to
routers through FastAPI dependencies. This is the only place that knows the concrete
classes; routers depend on ports.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import Request

from app.application.interfaces.routing import RoutingProvider
from app.application.use_cases.analyze_load import AnalyzeLoadUseCase
from app.config import Settings, get_settings
from app.domain.entities.vehicle import VehicleProfile
from app.domain.rules.recommendation import ProfitThresholds
from app.domain.value_objects.money import Money, RatePerMile
from app.infrastructure.ai.gemini import GeminiVisionProvider
from app.infrastructure.maps.openrouteservice import (
    OpenRouteServiceClient,
    OpenRouteServiceRoutingProvider,
)
from app.infrastructure.market.freight_datawatch import (
    FreightDataWatchClient,
    FreightDataWatchMarketProvider,
)
from app.infrastructure.persistence.sqlite import SqliteAnalysisRepository
from app.infrastructure.weather.nws import NwsWeatherProvider


class _UtcClock:
    """A clock that returns the current UTC time."""

    def now(self) -> datetime:
        return datetime.now(UTC)


def build_use_case(settings: Settings) -> AnalyzeLoadUseCase:
    """Build the fully wired use case. Callers own the provider lifetimes."""
    vision = GeminiVisionProvider(settings)
    market_client = FreightDataWatchClient(settings)
    market = FreightDataWatchMarketProvider(market_client)
    routing = _build_routing(settings)
    weather = NwsWeatherProvider(settings)
    repository = SqliteAnalysisRepository(settings.DATABASE_URL)
    return AnalyzeLoadUseCase(
        vision=vision,
        market=market,
        routing=routing,
        weather=weather,
        clock=_UtcClock(),
        repository=repository,
    )


def _build_routing(settings: Settings) -> RoutingProvider | None:
    """Build the routing adapter when a key is configured; otherwise ``None``."""
    try:
        client = OpenRouteServiceClient(settings)
        return OpenRouteServiceRoutingProvider(client)
    except Exception:
        return None


def resolve_use_case(request: Request) -> AnalyzeLoadUseCase:
    """FastAPI dependency: return the use case the app was composed with.

    The composition root hands its single instance through ``app.state`` so the HTTP
    surface and the Telegram bot share one provider client and repository. Apps built
    without one (tests) fall back to a freshly composed instance.
    """
    use_case = getattr(request.app.state, "use_case", None)
    if use_case is None:
        use_case = build_use_case(get_settings())
    return use_case


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
