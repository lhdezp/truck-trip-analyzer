"""Analysis contracts: the blocks of a load analysis.

Cost, profitability, compatibility and recommendation models live in the domain
because they are business concepts computed there. This module holds the remaining
blocks, which describe provider output.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

from app.application.schemas.base import Schema
from app.domain.value_objects.distance import Distance, Duration
from app.domain.value_objects.equipment import EquipmentType
from app.domain.value_objects.location import USLocation
from app.domain.value_objects.money import Money, RatePerMile
from app.domain.value_objects.provenance import DataSource

_MILE_TOLERANCE = Decimal("0.5")


class RouteAnalysis(Schema):
    """Distance and duration facts. Empty miles stay separate from loaded miles."""

    origin: USLocation | None = None
    destination: USLocation | None = None
    loaded_miles: Distance | None = None
    empty_miles: Distance | None = None
    total_miles: Distance | None = None
    duration: Duration | None = None
    provider: str | None = None
    routing_profile: str | None = None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _total_must_match_components(self) -> RouteAnalysis:
        if self.loaded_miles and self.empty_miles and self.total_miles:
            expected = self.loaded_miles.miles + self.empty_miles.miles
            if abs(expected - self.total_miles.miles) > _MILE_TOLERANCE:
                raise ValueError(
                    "total_miles must equal loaded_miles + empty_miles "
                    f"(expected {expected}, got {self.total_miles.miles})"
                )
        return self


class MarketScope(StrEnum):
    """Geographic granularity of a market reference."""

    NATIONAL = "national"
    REGIONAL = "regional"
    LANE = "lane"


class MarketReference(Schema):
    """One published or modeled rate used for comparison.

    ``scope`` and ``equipment`` are mandatory because comparing a national box truck
    estimate against a lane-level dry van rate would be a category error. Only
    provider data or explicit estimates are accepted as a basis; extracted or
    user-provided numbers are not market references.
    """

    rate_per_mile: RatePerMile
    equipment: EquipmentType
    scope: MarketScope
    basis: DataSource
    provider: str = Field(min_length=1)
    retrieved_at: datetime
    sample_notes: str | None = None

    @model_validator(mode="after")
    def _basis_must_be_provider_data(self) -> MarketReference:
        allowed = {DataSource.API, DataSource.ESTIMATED}
        if self.basis not in allowed:
            raise ValueError(
                f"market reference basis must be one of {sorted(allowed)}, got {self.basis}"
            )
        if self.rate_per_mile.amount < 0:
            raise ValueError("market rate cannot be negative")
        return self


class MarketAnalysis(Schema):
    """Comparison between the offer and available references."""

    offered_rate: RatePerMile | None = None
    references: list[MarketReference] = Field(default_factory=list)
    difference_percent: Decimal | None = None
    comparable: bool = False
    notes: list[str] = Field(default_factory=list)


class ReturnLoadOpportunity(Schema):
    """A verified return load, not a regional demand signal."""

    destination: USLocation
    rate_per_mile: RatePerMile | None = None
    source: DataSource
    retrieved_at: datetime
    notes: str | None = None


class DeadZoneAnalysis(Schema):
    """Destination conditions.

    ``destination_demand`` is a regional signal. It is **not** evidence that a return
    load exists, which is why verified opportunities are a separate, explicit list.
    """

    destination_demand: str | None = None
    demand_basis: DataSource | None = None
    return_data_available: bool = False
    return_loads: list[ReturnLoadOpportunity] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _cannot_claim_unavailable_returns(self) -> DeadZoneAnalysis:
        if not self.return_data_available and self.return_loads:
            raise ValueError("return_loads cannot be populated when return_data_available is false")
        return self


class Negotiation(Schema):
    """Negotiation envelope for the broker conversation."""

    minimum_acceptable: Money | None = None
    target_price: Money | None = None
    recommended_max: Money | None = None
    arguments: list[str] = Field(min_length=1)
    broker_message: str | None = None

    @model_validator(mode="after")
    def _bands_must_be_ordered(self) -> Negotiation:
        if (
            self.minimum_acceptable
            and self.target_price
            and self.minimum_acceptable.amount > self.target_price.amount
        ):
            raise ValueError("minimum_acceptable cannot exceed target_price")
        if (
            self.recommended_max
            and self.target_price
            and self.recommended_max.amount < self.target_price.amount
        ):
            raise ValueError("recommended_max cannot be below target_price")
        return self
