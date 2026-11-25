"""FastAPI application factory.

The factory is the single place where the HTTP surface is assembled. It registers
routers, middleware and the dependency container; it does not know the business
logic, which lives in the use case.

The lifespan also schedules the Telegram bot (V0.8) when a token is configured, so
the bot shares the server's event loop and process lifetime.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.application.use_cases.analyze_load import AnalyzeLoadUseCase
from app.config import Settings, get_settings
from app.presentation.api.deps import build_use_case
from app.presentation.api.routers import analysis, health, history

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application.

    ``settings`` is injected so tests can point at a local file or override secrets.
    The default reads the process-wide :func:`get_settings`.
    """
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # V0.8: schedule the Telegram bot on the running event loop.
        if resolved.TELEGRAM_BOT_TOKEN:
            from app.presentation.telegram.bot import start_bot_in_background

            use_case: AnalyzeLoadUseCase = build_use_case(resolved)
            start_bot_in_background(resolved, use_case)
            logger.info("Telegram bot scheduled on the server event loop")
        yield

    app = FastAPI(
        title=resolved.APP_NAME,
        version=__version__,
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.include_router(health.router)
    app.include_router(analysis.router)
    app.include_router(history.router)

    @app.exception_handler(500)
    async def _unhandled(_: object, info: object) -> dict[str, str]:
        # A 500 from FastAPI is a server-side failure; the client must not see a
        # stack trace. The detail is logged by the framework.
        return {"detail": "Internal server error"}

    return app
