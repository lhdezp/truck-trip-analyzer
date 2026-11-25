"""Process entrypoint.

V0.1 proves the foundation: configuration loads, logging is wired and the process
starts. V0.4 wires the Gemini vision adapter and V0.5 wires the Freight Data Watch
market adapter into the composition root. V0.6 wires the use case. V0.7 starts the
HTTP server. V0.8 starts the Telegram bot in the background. V0.9 persists results
in SQLite. V1.0 is the complete MVP: one process, one use case, two interfaces.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import uvicorn

from app import __version__
from app.application.interfaces.market import MarketDataProvider
from app.application.interfaces.routing import RoutingProvider
from app.application.interfaces.vision import VisionProvider
from app.application.interfaces.weather import WeatherProvider
from app.application.use_cases.analyze_load import AnalyzeLoadUseCase
from app.config import Settings, get_settings
from app.exceptions import ConfigurationError
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
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


class _UtcClock:
    """A clock that returns the current UTC time."""

    def now(self) -> datetime:
        return datetime.now(UTC)


def _build_use_case(settings: Settings) -> AnalyzeLoadUseCase:
    """Compose the use case with all available providers."""
    vision: VisionProvider = GeminiVisionProvider(settings)
    market_client = FreightDataWatchClient(settings)
    market: MarketDataProvider | None = FreightDataWatchMarketProvider(market_client)
    routing: RoutingProvider | None = _build_routing(settings)
    weather: WeatherProvider | None = NwsWeatherProvider(settings)
    repository = SqliteAnalysisRepository(settings.DATABASE_URL)
    return AnalyzeLoadUseCase(
        vision=vision,
        market=market,
        routing=routing,
        clock=_UtcClock(),
        repository=repository,
    )


def _build_routing(settings: Settings) -> RoutingProvider | None:
    """Build the routing adapter when a key is configured; otherwise ``None``."""
    try:
        client = OpenRouteServiceClient(settings)
        return OpenRouteServiceRoutingProvider(client)
    except ConfigurationError:
        return None


def main() -> int:
    """Bootstrap the application and return a process exit code."""
    settings = get_settings()
    configure_logging(settings)

    logger.info("%s %s starting in %s mode", settings.APP_NAME, __version__, settings.APP_ENV.value)
    logger.info(
        "Effective configuration: %s",
        json.dumps(settings.safe_summary(), ensure_ascii=False, sort_keys=True),
    )

    adapters: list[str] = []

    # V0.4: build the Gemini adapter. Construction validates model and key eagerly;
    # a missing credential is a configuration problem, not a reason to boot half-way.
    try:
        GeminiVisionProvider(settings)
        adapters.append("gemini")
    except ConfigurationError as exc:
        logger.error("Gemini adapter not ready: %s", exc)
        return 2

    # V0.5: build the Freight Data Watch market adapter.
    try:
        FreightDataWatchClient(settings)
        adapters.append("freight_datawatch")
    except ConfigurationError as exc:
        logger.error("Freight Data Watch adapter not ready: %s", exc)
        return 2

    logger.info("Adapters ready: %s", ", ".join(adapters))

    # V0.6: build the use case.
    _build_use_case(settings)

    # V0.7: start the HTTP server. The app is built lazily so the use case is
    # composed only when the first request arrives.
    from app.presentation.api.app import create_app

    app = create_app(settings)

    # V0.8: the Telegram bot is scheduled on the server's event loop by the
    # FastAPI lifespan. If a token is configured, the bot starts with the server
    # and shares its lifetime.
    if settings.TELEGRAM_BOT_TOKEN:
        logger.info("Telegram bot will start with the server (token configured)")

    logger.info("Starting HTTP server on %s:%s", settings.SERVER_HOST, settings.SERVER_PORT)
    uvicorn.run(app, host=settings.SERVER_HOST, port=settings.SERVER_PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
