"""Telegram bot: receives screenshots and replies with a recommendation.

The bot reuses the same :class:`AnalyzeLoadUseCase` as the API, so the business logic
lives in one place. The only Telegram-specific concern here is the user allowlist and
the formatting of the reply.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.application.schemas.extraction import ImageInput
from app.application.schemas.result import LoadAnalysisResult
from app.application.use_cases.analyze_load import AnalyzeLoadUseCase
from app.config import Settings

logger = logging.getLogger(__name__)

router = Router()


def _allowed_user_ids(settings: Settings) -> set[int]:
    return set(settings.telegram_allowed_user_ids)


async def _message_to_image_input(message: Message) -> ImageInput | None:
    """Convert a Telegram photo into an :class:`ImageInput`.

    The image must come from the message's ``photo`` or ``document`` part; anything
    else (a text note, a sticker) is rejected so the analysis does not run on empty
    input.
    """
    if message.photo:
        photo = message.photo[-1]
        bot = message.bot
        if bot is None:
            return None
        file = await bot.get_file(photo.file_id)
        if file.file_path is None:
            return None
        data = await bot.download_file(file.file_path)
        if data is None:
            return None
        return ImageInput(
            content=data.read(),
            media_type="image/jpeg",
            reference=f"telegram:{photo.file_id}",
        )
    if message.document:
        doc = message.document
        bot = message.bot
        if bot is None:
            return None
        file = await bot.get_file(doc.file_id)
        if file.file_path is None:
            return None
        data = await bot.download_file(file.file_path)
        if data is None:
            return None
        media_type = doc.mime_type or "image/jpeg"
        return ImageInput(
            content=data.read(),
            media_type=media_type,
            reference=f"telegram:{doc.file_id}",
        )
    return None


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Greet allowed users; refuse everyone else."""
    settings = _settings()
    if message.from_user is None or message.from_user.id not in _allowed_user_ids(settings):
        logger.warning(
            "Rejected /start from user %s", message.from_user.id if message.from_user else "?"
        )
        return
    await message.answer(
        "Truck Load Analyzer\n"
        "Send one or more screenshots of a load offer.\n"
        "I will extract the offer, compute the trip economics and recommend "
        "ACCEPT / NEGOTIATE / REJECT / INSUFFICIENT_DATA."
    )


@router.message(F.photo | F.document)
async def on_photo(message: Message) -> None:
    """Run the analysis on the received image(s) and reply with the decision."""
    settings = _settings()
    use_case = _use_case()
    if message.from_user is None or message.from_user.id not in _allowed_user_ids(settings):
        logger.warning(
            "Rejected photo from user %s", message.from_user.id if message.from_user else "?"
        )
        return

    image = await _message_to_image_input(message)
    if image is None:
        await message.answer("I could not read that image. Send a JPEG or PNG screenshot.")
        return

    from app.presentation.api.deps import DefaultLoadConfig

    result = await use_case.run(
        [image],
        config=DefaultLoadConfig(),
        context=f"telegram_user:{message.from_user.id}",
    )

    await message.answer(_format_reply(result))


def _format_reply(result: LoadAnalysisResult) -> str:
    """Build the Telegram reply from the analysis result."""
    lines: list[str] = []
    lines.append(f"Decision: {result.recommendation.decision.value.upper()}")
    if result.profitability and result.profitability.net_profit is not None:
        lines.append(f"Net profit: {result.profitability.net_profit}")
    if result.profitability and result.profitability.net_rpm is not None:
        lines.append(f"Net RPM: {result.profitability.net_rpm}")
    if result.market and result.market.difference_percent is not None:
        lines.append(
            f"Market diff: {result.market.difference_percent * 100:+.1f}% vs national estimate"
        )
    if result.warnings:
        lines.append("Warnings:")
        for w in result.warnings[:5]:
            lines.append(f"  - {w.code}: {w.message}")
    return "\n".join(lines)


def _settings() -> Settings:
    from app.config import get_settings

    return get_settings()


def _use_case() -> AnalyzeLoadUseCase:
    from app.config import get_settings
    from app.presentation.api.deps import build_use_case

    return build_use_case(get_settings())
