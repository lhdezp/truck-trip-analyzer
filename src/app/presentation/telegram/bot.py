"""Telegram bot composition.

The bot is built here, not in the handlers, so the handlers stay free of
configuration. The composition root (``main.py``) calls :func:`run_bot` when the
``TELEGRAM_BOT_TOKEN`` is set.

Two operational details matter:

- **One poller per token.** Telegram answers a second ``getUpdates`` with
  ``TelegramConflictError`` and aiogram retries forever, so the bot looks alive while
  it receives nothing. A preflight call turns that into an actionable error.
- **One use case.** The instance built by the composition root is injected into the
  handlers, so a photo does not build its own client and repository.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramConflictError

from app.application.use_cases.analyze_load import AnalyzeLoadUseCase
from app.config import Settings
from app.presentation.telegram.handlers import router

logger = logging.getLogger(__name__)


class BotAlreadyRunningError(RuntimeError):
    """Another process is already polling this bot token."""


def _build_dispatcher(use_case: AnalyzeLoadUseCase) -> Dispatcher:
    """Build the dispatcher with the use case available to every handler."""
    dispatcher = Dispatcher(use_case=use_case)
    dispatcher.include_router(router)
    return dispatcher


async def _ensure_single_poller(bot: Bot) -> None:
    """Fail fast when another process is polling this token.

    Polling and a webhook are mutually exclusive, so any registered webhook is dropped
    first: that is the documented precondition for ``getUpdates``. The probe itself
    uses no ``offset``, so it reads without confirming and cannot drop an update.
    """
    await bot.delete_webhook(drop_pending_updates=False)
    try:
        await bot.get_updates(timeout=0, limit=1)
    except TelegramConflictError as exc:
        raise BotAlreadyRunningError(
            "another process is polling this bot token; stop it (systemd, docker, "
            "tmux, a forgotten terminal) before starting this instance"
        ) from exc


async def run_bot(settings: Settings, use_case: AnalyzeLoadUseCase) -> None:
    """Start the Telegram bot and block until the process is interrupted."""
    token = settings.TELEGRAM_BOT_TOKEN.get_secret_value() if settings.TELEGRAM_BOT_TOKEN else ""
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not configured")

    bot = Bot(token=token)
    dispatcher = _build_dispatcher(use_case)
    await _ensure_single_poller(bot)
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
    if isinstance(exc, BotAlreadyRunningError):
        logger.error("Telegram bot disabled: %s", exc)
        return
    if exc is not None:
        logger.error("Telegram bot task failed: %s", exc)
