"""Provenance and confidence for every relevant datum.

The contract is deliberately explicit: a value never travels alone. It carries where
it came from, how trustworthy it is and which evidence supports it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from app.domain.base import ValueObject


class DataSource(StrEnum):
    """Where a value came from."""

    EXTRACTED = "extracted"
    CALCULATED = "calculated"
    API = "api"
    ESTIMATED = "estimated"
    USER_PROVIDED = "user_provided"


class ConfidenceLevel(StrEnum):
    """Qualitative confidence.

    Not a probability: it expresses data quality and consistency, not statistical
    certainty. Presenting it as a percentage would be a false precision.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class SourcedField[T](ValueObject):
    """A value plus its provenance.

    ``None`` at the field level means "unknown". A present field with a zero value
    means "known to be zero". The two must never be conflated.
    """

    value: T
    source: DataSource
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    evidence: str | None = None
    evidence_refs: tuple[str, ...] = ()
    observed_at: datetime | None = None
