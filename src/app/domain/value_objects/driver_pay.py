"""Driver pay policies.

Four mutually exclusive strategies modelled as a discriminated union. Using a union
instead of one model with optional fields makes an invalid state (an hourly policy
without an hourly rate, a percentage above 100) impossible to construct.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from app.domain.base import ValueObject
from app.domain.value_objects.distance import Distance, Duration
from app.domain.value_objects.money import Money, RatePerHour, RatePerMile


class DriverPayByMile(ValueObject):
    """Pay per mile driven.

    ``mile_basis`` is explicit because paying loaded-only versus total miles changes
    the cost of every load with deadhead.
    """

    strategy: Literal["per_mile"] = "per_mile"
    rate_per_mile: RatePerMile
    mile_basis: Literal["total", "loaded"] = "total"

    def amount_for(
        self,
        *,
        gross_revenue: Money,
        total_miles: Distance | None,
        loaded_miles: Distance | None,
        duration: Duration | None,
    ) -> Money | None:
        miles = total_miles if self.mile_basis == "total" else loaded_miles
        if miles is None:
            return None
        return Money(amount=miles.miles * self.rate_per_mile.amount)


class DriverPayByPercentage(ValueObject):
    """Pay as a share of gross revenue."""

    strategy: Literal["percentage"] = "percentage"
    percent: Decimal = Field(gt=0, le=100)

    def amount_for(
        self,
        *,
        gross_revenue: Money,
        total_miles: Distance | None,
        loaded_miles: Distance | None,
        duration: Duration | None,
    ) -> Money:
        return Money(amount=gross_revenue.amount * self.percent / Decimal(100))


class DriverPayHourly(ValueObject):
    """Pay per hour on duty. Requires a duration to be computable."""

    strategy: Literal["hourly"] = "hourly"
    rate_per_hour: RatePerHour

    def amount_for(
        self,
        *,
        gross_revenue: Money,
        total_miles: Distance | None,
        loaded_miles: Distance | None,
        duration: Duration | None,
    ) -> Money | None:
        if duration is None:
            return None
        return Money(amount=self.rate_per_hour.amount * duration.hours)


class DriverPayFixed(ValueObject):
    """A fixed amount for the trip, independent of miles and hours."""

    strategy: Literal["fixed"] = "fixed"
    amount: Money

    def amount_for(
        self,
        *,
        gross_revenue: Money,
        total_miles: Distance | None,
        loaded_miles: Distance | None,
        duration: Duration | None,
    ) -> Money:
        return self.amount


DriverPayPolicy = Annotated[
    DriverPayByMile | DriverPayByPercentage | DriverPayHourly | DriverPayFixed,
    Field(discriminator="strategy"),
]
