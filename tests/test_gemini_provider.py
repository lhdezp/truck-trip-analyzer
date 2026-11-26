"""Gemini adapter: what leaves the process and how a failure is reported.

These tests never touch the network. They assert the two things that were wrong in
production: the screenshot must travel as an image part next to the instructions, and
a failed call must say *why* it failed instead of looking like an unreadable image.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest
from google.genai import types

from app.application.schemas.extraction import ImageInput
from app.config import Settings
from app.exceptions import (
    PROVIDER_KIND_PAYLOAD_TOO_LARGE,
    PROVIDER_KIND_UNAVAILABLE,
    ProviderError,
)
from app.infrastructure.ai.gemini.provider import GeminiVisionProvider, _build_contents
from app.infrastructure.ai.gemini.wire import (
    WireExtraction,
    WireLocation,
    WireOffer,
    WirePrice,
)

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)
JPEG_HEADER = b"\xff\xd8\xff"


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"GEMINI_MODEL": "gemini-test", "GEMINI_API_KEY": "test-key"}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _image(reference: str = "telegram:abc", content: bytes = PNG) -> ImageInput:
    return ImageInput(content=content, media_type="image/png", reference=reference)


def _wire_response() -> types.GenerateContentResponse:
    wire = WireExtraction(
        offers=[
            WireOffer(
                origin=WireLocation(city="Dallas", state="TX", evidence="Dallas, TX"),
                destination=WireLocation(city="Atlanta", state="GA", evidence="Atlanta, GA"),
                price=WirePrice(total_usd=1250.0, evidence="$1,250"),
            )
        ]
    )
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(content=types.Content(parts=[types.Part(text=wire.model_dump_json())]))
        ]
    )


class _VendorError(Exception):
    """Stand-in for a google-genai ClientError: the adapter only reads the status."""

    status_code = 403

    def __str__(self) -> str:
        return "403 Forbidden. <html>blocked</html>"


def test_contents_carry_the_instructions_and_the_image_as_an_image_part() -> None:
    contents = _build_contents(_image(), context="telegram_user:1")

    assert isinstance(contents[0], str)
    assert "telegram:abc" in contents[0]
    assert "Transcribe this screenshot" in contents[0]

    part = contents[1]
    assert isinstance(part, types.Part)
    assert part.inline_data is not None
    assert part.inline_data.mime_type == "image/png"
    assert part.inline_data.data == PNG


async def test_transport_failure_reports_status_kind_and_reason() -> None:
    async def generate(**_: Any) -> types.GenerateContentResponse:
        raise _VendorError

    provider = GeminiVisionProvider(_settings(), generate=generate)

    with pytest.raises(ProviderError) as raised:
        await provider.extract_load([_image()])

    error = raised.value
    assert error.kind == PROVIDER_KIND_UNAVAILABLE
    assert error.details["status_code"] == 403
    assert error.details["media_type"] == "image/png"
    assert error.details["size_bytes"] == len(PNG)
    assert "403 Forbidden" in str(error.details["reason"])


async def test_oversized_request_is_rejected_before_calling_the_api() -> None:
    calls = 0

    async def generate(**_: Any) -> types.GenerateContentResponse:
        nonlocal calls
        calls += 1
        return _wire_response()

    provider = GeminiVisionProvider(
        _settings(GEMINI_MAX_REQUEST_BYTES=1024 * 1024),
        generate=generate,
    )
    big = ImageInput(
        content=JPEG_HEADER + b"x" * (1024 * 1024),
        media_type="image/jpeg",
        reference="telegram:big",
    )

    with pytest.raises(ProviderError) as raised:
        await provider.extract_load([big])

    assert raised.value.kind == PROVIDER_KIND_PAYLOAD_TOO_LARGE
    assert raised.value.details["largest_image"] == "telegram:big"
    assert calls == 0


async def test_one_failed_image_does_not_hide_the_readable_one() -> None:
    async def generate(*, contents: Any, **_: Any) -> types.GenerateContentResponse:
        if "telegram:broken" in contents[0]:
            raise _VendorError
        return _wire_response()

    provider = GeminiVisionProvider(_settings(), generate=generate)
    extraction = await provider.extract_load([_image("telegram:broken"), _image("telegram:ok")])

    assert extraction.images_analyzed == 1
    assert "image_failed:telegram:broken" in extraction.warnings
