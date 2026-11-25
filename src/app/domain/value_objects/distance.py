"""Distance and duration value objects.

Loaded, empty and total miles are distinct concepts in the financial model, so the
unit lives in the type: a ``Distance`` is always miles, never hours or dollars.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import Field, field_validator

from app.domain.base import ValueObject

_TENTH_MILE = Decimal("0.1")
_HUNDREDTH_HOUR = Decimal("0.01")


class Distance(ValueObject):
    """A non-negative distance in miles."""

    miles: Decimal = Field(ge=0)

    @field_validator("miles")
    @classmethod
    def _round_to_tenth(cls, value: Decimal) -> Decimal:
        return value.quantize(_TENTH_MILE, rounding=ROUND_HALF_UP)

    @property
    def is_zero(self) -> bool:
        return self.miles == 0

    def __str__(self) -> str:
        return f"{self.miles:,.1f} mi"


class Duration(ValueObject):
    """A non-negative duration in hours."""

    hours: Decimal = Field(ge=0)

    @field_validator("hours")
    @classmethod
    def _round_to_hundredth(cls, value: Decimal) -> Decimal:
        return value.quantize(_HUNDREDTH_HOUR, rounding=ROUND_HALF_UP)

    def __str__(self) -> str:
        return f"{self.hours:.2f} h"
