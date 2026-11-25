"""Vision extraction port."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.application.schemas.extraction import ImageInput, LoadExtraction


class VisionProvider(Protocol):
    """Extracts a structured load offer from one or more screenshots.

    Implementations must not invent absent data and must preserve per-field evidence.
    Consolidation of multiple images belongs to the adapter only when the provider
    natively supports it; otherwise the use case merges single-image extractions.
    """

    async def extract_load(
        self,
        images: Sequence[ImageInput],
        *,
        context: str | None = None,
    ) -> LoadExtraction: ...
