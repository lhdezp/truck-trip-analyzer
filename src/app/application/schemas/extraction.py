"""Extraction contracts: what the vision provider returns."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field

from app.application.schemas.base import Schema
from app.domain.entities.load import LoadOffer

MAX_IMAGE_BYTES = 8 * 1024 * 1024


class ImageInput(Schema):
    """One image handed to a vision provider.

    The size limit lives in the contract, not in the HTTP layer: every entry point
    (API, Telegram, CLI) must enforce the same ceiling.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: bytes = Field(min_length=1, max_length=MAX_IMAGE_BYTES)
    media_type: Literal["image/jpeg", "image/png", "image/webp"]
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
