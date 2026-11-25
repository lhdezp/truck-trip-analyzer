"""Dimensions value object, in inches."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import Field, field_validator

from app.domain.base import ValueObject

_TENTH_INCH = Decimal("0.1")


class Dimensions(ValueObject):
    """Interior or cargo dimensions in inches. Every axis must be positive."""

    length_in: Decimal = Field(gt=0)
    width_in: Decimal = Field(gt=0)
    height_in: Decimal = Field(gt=0)

    @field_validator("length_in", "width_in", "height_in")
    @classmethod
    def _round_to_tenth(cls, value: Decimal) -> Decimal:
        return value.quantize(_TENTH_INCH, rounding=ROUND_HALF_UP)
