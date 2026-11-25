"""Wire shape of Freight Data Watch's market endpoints.

These models mirror the payloads actually returned by the API (recorded 2026-11-24
against the live service), not a guess from the portal. The portal documents paths
and auth but not response bodies, so field names and units come from recorded
responses, never from inference.

``extra="ignore"`` because a provider that adds a field must not fail the whole call;
``extra="forbid"`` would turn every provider change into an outage.

Only the subset of fields the analysis actually uses is declared. A missing optional
field means "the provider did not report it", which maps to a ``None`` in the domain,
not to a default.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class WireModel(BaseModel):
    """Transport shape for a provider payload."""

    model_config = ConfigDict(extra="ignore")


class WireMonthlyRate(WireModel):
    """One point of the historical rate series."""

    month: str = Field(min_length=1, description="YYYY-MM")
    rate: float


class WireEquipmentRates(WireModel):
    """Rates for one equipment category as reported by the provider."""

    avg_rate: float | None = Field(default=None, alias="avgRate")
    rate_change: float | None = Field(default=None, alias="rateChange")
    availability: str | None = None
    avg_load_weight: float | None = Field(default=None, alias="avgLoadWeight")
    demand_trend: str | None = Field(default=None, alias="demandTrend")
    historical_monthly: list[WireMonthlyRate] = Field(
        default_factory=list, alias="historicalMonthly"
    )
    top_lanes: list[str] = Field(default_factory=list, alias="topLanes")

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class WireSpecialized(WireModel):
    """The `/market/specialized` payload: national modeled estimates per equipment."""

    equipment: dict[str, WireEquipmentRates] = Field(default_factory=dict)
    data_type: str | None = Field(default=None, alias="dataType")
    geography: str | None = None
    methodology: str | None = None
    attribution: str | None = None
    last_updated: str | None = Field(default=None, alias="lastUpdated")

    model_config = ConfigDict(extra="ignore", populate_by_name=True)
