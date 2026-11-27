"""Bot startup guards.

A second ``getUpdates`` on the same token makes Telegram terminate the first one and
aiogram retries forever, so the bot looks alive while it is deaf. The preflight must
turn that into a clear failure.
"""

from __future__ import annotations

from typing import Any

import pytest
from aiogram.exceptions import TelegramConflictError

from app.presentation.telegram.bot import BotAlreadyRunningError, _ensure_single_poller


class _StubBot:
    def __init__(self, *, conflict: bool) -> None:
        self._conflict = conflict
        self.calls: list[dict[str, Any]] = []
        self.webhook_deleted = False

    async def delete_webhook(self, **_: Any) -> bool:
        self.webhook_deleted = True
        return True

    async def get_updates(self, **kwargs: Any) -> list[object]:
        self.calls.append(kwargs)
        if self._conflict:
            raise TelegramConflictError(
                method=None, message="terminated by other getUpdates request"
            )
        return []


async def test_preflight_passes_when_no_other_poller_exists() -> None:
    bot = _StubBot(conflict=False)

    await _ensure_single_poller(bot)  # type: ignore[arg-type]

    assert bot.webhook_deleted is True
    assert bot.calls == [{"timeout": 0, "limit": 1}]


async def test_preflight_fails_loudly_when_another_poller_owns_the_token() -> None:
    bot = _StubBot(conflict=True)

    with pytest.raises(BotAlreadyRunningError) as raised:
        await _ensure_single_poller(bot)  # type: ignore[arg-type]

    assert "another process is polling this bot token" in str(raised.value)
