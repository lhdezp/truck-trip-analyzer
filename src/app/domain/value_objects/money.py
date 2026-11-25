"""Monetary value objects.

Amounts use ``Decimal`` and are rounded to cents at construction. Binary floats are
forbidden in the financial path: ``0.1 + 0.2`` must not decide whether a load is
profitable.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import field_validator

from app.domain.base import ValueObject

_CENTS = Decimal("0.01")
_PER_MILE_PRECISION = Decimal("0.0001")
_PER_HOUR_PRECISION = Decimal("0.01")


class Money(ValueObject):
    """An amount of money. Negative values are allowed (net profit can be negative)."""

    amount: Decimal
    currency: Literal["USD"] = "USD"

    @field_validator("amount")
    @classmethod
    def _round_to_cents(cls, value: Decimal) -> Decimal:
        return value.quantize(_CENTS, rounding=ROUND_HALF_UP)

    def __str__(self) -> str:
        return f"${self.amount:,.2f}"


class RatePerMile(ValueObject):
    """A rate expressed in dollars per mile.

    The sign is meaningful: gross RPM and market rates are non-negative, but net RPM
    is negative whenever a load loses money. Market references enforce the
    non-negative constraint where it belongs.
    """

    amount: Decimal
    currency: Literal["USD"] = "USD"

    @field_validator("amount")
    @classmethod
    def _round_to_per_mile_precision(cls, value: Decimal) -> Decimal:
        return value.quantize(_PER_MILE_PRECISION, rounding=ROUND_HALF_UP)

    def __str__(self) -> str:
        return f"${self.amount:.4f}/mi"


class RatePerHour(ValueObject):
    """An amount of money per hour, used for profit per hour and hourly pay."""

    amount: Decimal
    currency: Literal["USD"] = "USD"

    @field_validator("amount")
    @classmethod
    def _round_to_cents(cls, value: Decimal) -> Decimal:
        return value.quantize(_PER_HOUR_PRECISION, rounding=ROUND_HALF_UP)

    def __str__(self) -> str:
        return f"${self.amount:,.2f}/h"
