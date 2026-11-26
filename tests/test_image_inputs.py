"""Image input contracts: the bytes decide what an image is."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.schemas.extraction import (
    ImageInput,
    normalize_image_media_type,
    sniff_image_media_type,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 8
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBPVP8 "


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("image/jpeg", "image/jpeg"),
        ("image/jpg", "image/jpeg"),
        ("image/jpg; charset=binary", "image/jpeg"),
        ("IMAGE/PNG", "image/png"),
        ("image/webp", "image/webp"),
        ("application/pdf", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_image_media_type(raw: str | None, expected: str | None) -> None:
    assert normalize_image_media_type(raw) == expected


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (WEBP, "image/webp"),
        (b"%PDF-1.7", None),
        (b"", None),
    ],
)
def test_sniff_image_media_type(content: bytes, expected: str | None) -> None:
    assert sniff_image_media_type(content) == expected


def test_image_input_rejects_empty_content() -> None:
    with pytest.raises(ValidationError):
        ImageInput(content=b"", media_type="image/png", reference="telegram:x")
