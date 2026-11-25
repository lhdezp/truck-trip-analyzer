"""Weight value object.

Pounds, not kilograms: the target market is the United States and every load board,
provider and regulation in scope uses pounds. Converting silently would create the
kind of unit error this project cannot afford.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import Field, field_validator

from app.domain.base import ValueObject

_TENTH_POUND = Decimal("0.1")


class Weight(ValueObject):
    """A non-negative weight in pounds."""

    pounds: Decimal = Field(ge=0)

    @field_validator("pounds")
    @classmethod
    def _round_to_tenth(cls, value: Decimal) -> Decimal:
        return value.quantize(_TENTH_POUND, rounding=ROUND_HALF_UP)

    def __str__(self) -> str:
        return f"{self.pounds:,.1f} lb"
