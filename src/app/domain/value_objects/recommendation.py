"""Recommendation value objects."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from app.domain.base import ValueObject
from app.domain.value_objects.provenance import ConfidenceLevel


class RecommendationDecision(StrEnum):
    """The four possible outcomes of an analysis."""

    ACCEPT = "accept"
    NEGOTIATE = "negotiate"
    REJECT = "reject"
    INSUFFICIENT_DATA = "insufficient_data"


class FinalRecommendation(ValueObject):
    """A decision with its justification. Reasons are mandatory by design."""

    decision: RecommendationDecision
    reasons: tuple[str, ...] = Field(min_length=1)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
