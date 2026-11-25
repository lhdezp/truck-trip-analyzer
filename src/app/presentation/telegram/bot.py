"""Telegram bot composition.

The bot is built here, not in the handlers, so the handlers stay free of
configuration. The composition root (``main.py``) calls :func:`run_bot` when the
``TELEGRAM_BOT_TOKEN`` is set.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.application.use_cases.analyze_load import AnalyzeLoadUseCase
from app.config import Settings
from app.presentation.telegram.handlers import router

logger = logging.getLogger(__name__)


def _build_dispatcher(settings: Settings, use_case: AnalyzeLoadUseCase) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


async def run_bot(settings: Settings, use_case: AnalyzeLoadUseCase) -> None:
    """Start the Telegram bot and block until the process is interrupted."""
    token = settings.TELEGRAM_BOT_TOKEN.get_secret_value() if settings.TELEGRAM_BOT_TOKEN else ""
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not configured")

    bot = Bot(token=token)
    dispatcher = _build_dispatcher(settings, use_case)
    logger.info("Telegram bot started; polling for updates")
    await dispatcher.start_polling(bot)


def start_bot_in_background(settings: Settings, use_case: AnalyzeLoadUseCase) -> None:
    """Run the bot in a background task so the HTTP server stays the main thread.

    This must be called from inside a running event loop (the one uvicorn creates).
    The bot task is not awaited: it runs until the process exits.
    """
    task = asyncio.create_task(run_bot(settings, use_case))
    task.add_done_callback(_log_bot_exit)


def _log_bot_exit(task: asyncio.Task[None]) -> None:
    exc = task.exception()
    if exc is not None:
        logger.error("Telegram bot task failed: %s", exc)
