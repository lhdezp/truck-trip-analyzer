"""Telegram bot: receives screenshots and replies with a recommendation.

The bot reuses the same :class:`AnalyzeLoadUseCase` as the API, so the business logic
lives in one place. The only Telegram-specific concerns here are the user allowlist,
turning a message into a validated :class:`ImageInput`, and the formatting of the
reply.

Everything that can go wrong *before* the analysis (an unsupported document, a file
Telegram refuses to serve, an image over the size ceiling) is answered with a message
the user can act on. A handler that dies silently is worse than a rejection: the user
resends the same image and gets the same silence.
"""

from __future__ import annotations

import logging
from typing import NoReturn

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message

from app.application.schemas.extraction import (
    MAX_IMAGE_BYTES,
    ImageInput,
    normalize_image_media_type,
    sniff_image_media_type,
)
from app.application.schemas.result import LoadAnalysisResult
from app.application.use_cases.analyze_load import (
    CODE_VISION_FAILED,
    CODE_VISION_PAYLOAD_TOO_LARGE,
    CODE_VISION_UNAUTHORIZED,
    CODE_VISION_UNAVAILABLE,
    AnalyzeLoadUseCase,
)
from app.config import Settings

logger = logging.getLogger(__name__)

router = Router()

# Codes already turned into a headline by :func:`_format_reply`; repeating them in the
# generic warning list would say the same thing twice.
_VISION_CODES = frozenset(
    {
        CODE_VISION_FAILED,
        CODE_VISION_PAYLOAD_TOO_LARGE,
        CODE_VISION_UNAUTHORIZED,
        CODE_VISION_UNAVAILABLE,
    }
)


class _ImageRejected(Exception):
    """The message cannot become a valid image.

    The message is written for the user, not for the log, so it can be sent as-is.
    """


def _reject(reason: str) -> NoReturn:
    raise _ImageRejected(reason)


def _allowed_user_ids(settings: Settings) -> set[int]:
    return set(settings.telegram_allowed_user_ids)


async def _download(message: Message, *, file_id: str, reference: str) -> bytes:
    """Fetch the bytes of one Telegram file, or reject with an actionable reason."""
    bot = message.bot
    if bot is None:
        _reject("I could not download the image in this context. Forward it to the chat.")
    try:
        file = await bot.get_file(file_id)
        if file.file_path is None:
            _reject(
                "Telegram did not hand me the file (this happens with very large files). "
                "Send the screenshot as a photo."
            )
        stream = await bot.download_file(file.file_path)
    except TelegramAPIError as exc:
        logger.warning("Telegram could not serve %s: %s", reference, exc)
        _reject("Telegram could not serve that file. Forward it or send it as a photo.")
    if stream is None:
        _reject("The file arrived empty. Send the screenshot again.")
    return stream.read()


async def _message_to_image_input(message: Message) -> ImageInput:
    """Convert a Telegram photo or image document into a validated :class:`ImageInput`.

    The media type is taken from the bytes, not from the label: Telegram reports
    ``image/jpg`` for some documents and mislabels others, and a wrong ``mime_type``
    is a request Gemini refuses. The label is only used to explain a rejection.
    """
    if message.photo:
        photo = message.photo[-1]
        reference = f"telegram:{photo.file_id}"
        declared_raw: str | None = "image/jpeg"
        content = await _download(message, file_id=photo.file_id, reference=reference)
    elif message.document:
        document = message.document
        reference = f"telegram:{document.file_id}"
        declared_raw = document.mime_type
        content = await _download(message, file_id=document.file_id, reference=reference)
    else:
        _reject("Send me a photo or an image file (JPEG, PNG or WebP).")

    if not content:
        _reject("The file arrived empty. Send the screenshot again.")
    if len(content) > MAX_IMAGE_BYTES:
        _reject(
            f"The image is {len(content) / (1024 * 1024):.1f} MB and the maximum is "
            f"{MAX_IMAGE_BYTES // (1024 * 1024)} MB. Send it as a photo: Telegram compresses it."
        )

    sniffed = sniff_image_media_type(content)
    if sniffed is None:
        declared = normalize_image_media_type(declared_raw)
        detail = f" ({declared})" if declared else f" ({declared_raw or 'unknown type'})"
        _reject(f"I could not recognize that image as JPEG, PNG or WebP{detail}.")

    declared = normalize_image_media_type(declared_raw)
    if declared is not None and declared != sniffed:
        logger.info(
            "Declared media type %s does not match the bytes (%s) for %s; using the bytes",
            declared,
            sniffed,
            reference,
        )

    return ImageInput(content=content, media_type=sniffed, reference=reference)


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
async def on_photo(message: Message, use_case: AnalyzeLoadUseCase) -> None:
    """Run the analysis on the received image(s) and reply with the decision.

    ``use_case`` is injected by the dispatcher from the composition root, so every
    photo reuses the same provider clients and repository.
    """
    settings = _settings()
    if message.from_user is None or message.from_user.id not in _allowed_user_ids(settings):
        logger.warning(
            "Rejected photo from user %s", message.from_user.id if message.from_user else "?"
        )
        return

    try:
        image = await _message_to_image_input(message)
    except _ImageRejected as exc:
        logger.info("Rejected image from %s: %s", message.from_user.id, exc)
        await message.answer(str(exc))
        return

    from app.presentation.api.deps import DefaultLoadConfig

    try:
        result = await use_case.run(
            [image],
            config=DefaultLoadConfig(),
            context=_context_for(message),
        )
    except Exception:
        # The use case degrades provider failures into warnings; reaching this point
        # means a bug. Answer anyway so the user is not left waiting on silence.
        logger.exception("Analysis failed for %s", image.reference)
        await message.answer("The analysis broke on that screenshot. Try again in a moment.")
        return

    await message.answer(_format_reply(result))


def _context_for(message: Message) -> str:
    """Caller context sent with the image: who asked and, if present, their caption."""
    user_id = message.from_user.id if message.from_user else "unknown"
    parts = [f"telegram_user:{user_id}"]
    caption = (message.caption or "").strip()
    if caption:
        parts.append(caption[:500])
    return "\n".join(parts)


def _format_reply(result: LoadAnalysisResult) -> str:
    """Build the Telegram reply from the analysis result."""
    codes = {warning.code for warning in result.warnings}
    lines: list[str] = []
    if CODE_VISION_UNAUTHORIZED in codes:
        lines.append("AI service rejected the credential. Check GEMINI_API_KEY before retrying.")
    elif CODE_VISION_UNAVAILABLE in codes:
        lines.append("AI service is unavailable right now. Retry in a few minutes.")
    elif CODE_VISION_PAYLOAD_TOO_LARGE in codes:
        lines.append(
            "The screenshots are too large for the AI service. Send fewer or lighter ones."
        )
    elif CODE_VISION_FAILED in codes:
        lines.append("I could not read that screenshot. Send a clearer or complete one.")

    lines.append(f"Decision: {result.recommendation.decision.value.upper()}")
    if result.profitability and result.profitability.net_profit is not None:
        lines.append(f"Net profit: {result.profitability.net_profit}")
    if result.profitability and result.profitability.net_rpm is not None:
        lines.append(f"Net RPM: {result.profitability.net_rpm}")
    if result.market and result.market.difference_percent is not None:
        lines.append(
            f"Market diff: {result.market.difference_percent * 100:+.1f}% vs national estimate"
        )

    others = [warning for warning in result.warnings if warning.code not in _VISION_CODES]
    if others:
        lines.append("Warnings:")
        for warning in others[:5]:
            lines.append(f"  - {warning.code}: {warning.message}")
    return "\n".join(lines)


def _settings() -> Settings:
    from app.config import get_settings

    return get_settings()
