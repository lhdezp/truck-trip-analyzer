"""Persistence port.

The analysis pipeline records its results behind this port so the use case never
knows whether storage is SQLite, Postgres or in-memory.
"""

from __future__ import annotations

from typing import Protocol

from app.application.schemas.result import LoadAnalysisResult


class AnalysisRepository(Protocol):
    """Stores and retrieves finished analyses."""

    async def save(self, result: LoadAnalysisResult) -> str:
        """Persist one analysis and return its identifier."""
        ...

    async def get(self, analysis_id: str) -> LoadAnalysisResult | None:
        """Fetch one analysis by id; ``None`` when it does not exist."""
        ...

    async def list_recent(self, *, limit: int = 20) -> list[LoadAnalysisResult]:
        """Return the most recent analyses, newest first."""
        ...
