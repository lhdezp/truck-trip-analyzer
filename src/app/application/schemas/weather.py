"""Weather contracts.

Weather is enrichment, never a prerequisite: ``available=False`` is a valid outcome
and must not block the financial analysis.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import model_validator

from app.application.schemas.base import Schema
from app.domain.value_objects.location import USLocation


class WeatherSeverity(StrEnum):
    """Operational impact of the conditions."""

    NONE = "none"
    MODERATE = "moderate"
    SEVERE = "severe"


class WeatherCondition(Schema):
    """Conditions for one point of the trip."""

    location: USLocation
    summary: str
    severity: WeatherSeverity = WeatherSeverity.NONE
    temperature_f: Decimal | None = None
    alerts: tuple[str, ...] = ()


class WeatherRequest(Schema):
    """Weather lookup for the two ends of a route."""

    origin: USLocation
    destination: USLocation
    departure: datetime | None = None


class WeatherReport(Schema):
    """Provider answer for a route. Absence of data is explicit."""

    provider: str
    retrieved_at: datetime
    available: bool
    origin: WeatherCondition | None = None
    destination: WeatherCondition | None = None
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _availability_must_match_payload(self) -> WeatherReport:
        has_conditions = self.origin is not None or self.destination is not None
        if self.available != has_conditions:
            raise ValueError(
                "available must be true exactly when at least one condition is present"
            )
        return self
