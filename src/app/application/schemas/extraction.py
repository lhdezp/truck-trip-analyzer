"""Extraction contracts: what the vision provider returns."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field

from app.application.schemas.base import Schema
from app.domain.entities.load import LoadOffer

MAX_IMAGE_BYTES = 8 * 1024 * 1024

ImageMediaType = Literal["image/jpeg", "image/png", "image/webp"]

# Media types the vision providers accept, plus the aliases senders actually use.
# Telegram reports ``image/jpg`` for some documents and appends parameters such as
# ``; charset=binary``; both must be normalised before :class:`ImageInput` validates.
_MEDIA_TYPE_ALIASES: dict[str, ImageMediaType] = {
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
    "image/png": "image/png",
    "image/x-png": "image/png",
    "image/webp": "image/webp",
}


def normalize_image_media_type(raw: str | None) -> ImageMediaType | None:
    """Return a supported media type, or ``None`` when the input cannot be read.

    Normalising at the boundary means a caller never has to guess why Pydantic
    rejected ``image/jpg`` and the user always gets a message naming the formats.
    """
    if not raw:
        return None
    base = raw.split(";", 1)[0].strip().lower()
    return _MEDIA_TYPE_ALIASES.get(base)


def sniff_image_media_type(content: bytes) -> ImageMediaType | None:
    """Identify the image from its magic bytes, or ``None`` when it is not one.

    The bytes are the truth. A sender can label a PNG as ``image/jpeg``; the vision
    API then refuses the request. Sniffing first makes the declared label advisory.
    """
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


class ImageInput(Schema):
    """One image handed to a vision provider.

    The size limit lives in the contract, not in the HTTP layer: every entry point
    (API, Telegram, CLI) must enforce the same ceiling.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: bytes = Field(min_length=1, max_length=MAX_IMAGE_BYTES)
    media_type: ImageMediaType
    reference: str = Field(min_length=1, description="Stable id, e.g. 'telegram:file_id'")

    @property
    def size_bytes(self) -> int:
        return len(self.content)


class Contradiction(Schema):
    """Two or more captures disagree about the same field."""

    field: str = Field(min_length=1)
    description: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()


class LoadExtraction(Schema):
    """Result of reading one or more captures of a single offer.

    ``ambiguous_fields`` names fields that were read but cannot be trusted without a
    clarification. Nothing here is invented: absent data stays absent in ``load``.
    ``warnings`` carries degradation signals that are not about a field, such as an
    image that could not be processed or a screenshot that was not a load offer.
    """

    load: LoadOffer
    contradictions: list[Contradiction] = Field(default_factory=list)
    ambiguous_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    images_analyzed: int = Field(ge=0)
    provider: str = Field(min_length=1)
    model: str | None = None
    raw_text: str | None = None
    extracted_at: datetime
