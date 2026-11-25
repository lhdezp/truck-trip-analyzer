"""Top-level analysis result: the nine blocks plus cross-cutting metadata."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.application.schemas.analysis import (
    DeadZoneAnalysis,
    MarketAnalysis,
    Negotiation,
    RouteAnalysis,
)
from app.application.schemas.base import Schema
from app.domain.entities.load import LoadField, LoadOffer
from app.domain.value_objects.compatibility import VehicleCompatibility
from app.domain.value_objects.costs import CostBreakdown
from app.domain.value_objects.profitability import Profitability
from app.domain.value_objects.provenance import ConfidenceLevel
from app.domain.value_objects.recommendation import FinalRecommendation


class Severity(StrEnum):
    """How much a warning should worry the user."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AnalysisWarning(Schema):
    """A structured warning. Codes are stable; messages are human readable."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: Severity = Severity.WARNING


class SourceRecord(Schema):
    """One external source consulted while producing the analysis."""

    provider: str = Field(min_length=1)
    kind: str = Field(min_length=1, description="ai, market, routing, weather, persistence")
    retrieved_at: datetime | None = None
    reference: str | None = None


class LoadAnalysisResult(Schema):
    """Stable response contract shared by every interface.

    Blocks are optional because a provider outage must degrade the analysis, not
    crash it. The recommendation is always present, and it is allowed to be
    ``INSUFFICIENT_DATA`` when the missing pieces make a decision irresponsible.
    """

    load: LoadOffer
    route: RouteAnalysis | None = None
    vehicle_compatibility: VehicleCompatibility | None = None
    costs: CostBreakdown | None = None
    profitability: Profitability | None = None
    market: MarketAnalysis | None = None
    dead_zone: DeadZoneAnalysis | None = None
    negotiation: Negotiation | None = None
    recommendation: FinalRecommendation

    missing_fields: list[LoadField] = Field(default_factory=list)
    warnings: list[AnalysisWarning] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    sources: list[SourceRecord] = Field(default_factory=list)
    calculated_at: datetime
    market_data_timestamp: datetime | None = None

    @model_validator(mode="after")
    def _market_timestamp_required_with_references(self) -> LoadAnalysisResult:
        if self.market and self.market.references and self.market_data_timestamp is None:
            raise ValueError("market_data_timestamp is required when market references exist")
        return self
