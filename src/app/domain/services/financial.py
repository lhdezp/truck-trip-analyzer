"""Deterministic financial engine.

No I/O, no AI, no hidden defaults. Every number is either derived from an input or
reported as missing. When an input is absent the affected metric stays ``None`` and is
named in ``missing_inputs``; it is never replaced by zero.
"""

from __future__ import annotations

from decimal import Decimal

from app.domain.entities.vehicle import VehicleProfile
from app.domain.exceptions import DomainValidationError
from app.domain.value_objects.costs import CostBreakdown
from app.domain.value_objects.distance import Distance, Duration
from app.domain.value_objects.driver_pay import DriverPayByMile, DriverPayHourly, DriverPayPolicy
from app.domain.value_objects.money import Money, RatePerHour, RatePerMile
from app.domain.value_objects.profitability import FinancialEstimate, Profitability

FIXED_COST_NOT_ALLOCATED = "Monthly fixed costs are not allocated to a single load."
OTHER_COSTS_ASSUMED_ZERO = "Other costs were not declared and are treated as zero."
TOLLS_FROM_RATE = "Tolls are estimated from the vehicle toll rate per mile."
DRIVER_PAY_TOTAL_MILES = "Per-mile driver pay uses total miles (loaded plus empty)."
DRIVER_PAY_LOADED_MILES = "Per-mile driver pay uses loaded miles only."


def _unique(items: list[str]) -> tuple[str, ...]:
    """Deduplicate while preserving the order in which gaps were discovered."""
    return tuple(dict.fromkeys(items))


class FinancialEngine:
    """Cost and profitability calculator for a single load and vehicle."""

    def calculate(
        self,
        *,
        price_offered: Money,
        vehicle: VehicleProfile,
        loaded_miles: Distance | None,
        empty_miles: Distance | None,
        duration: Duration | None,
        factoring_rate: Decimal | None = None,
        fuel_price_per_gallon: Money | None = None,
        tolls: Money | None = None,
        other_costs: Money | None = None,
        driver_pay: DriverPayPolicy | None = None,
    ) -> FinancialEstimate:
        """Compute costs and profitability.

        ``factoring_rate`` is a fraction between 0 and 1 (0.03 = 3 %). Inputs left as
        ``None`` are reported as missing instead of being assumed.
        """
        if price_offered.amount < 0:
            raise DomainValidationError("price_offered cannot be negative")
        if factoring_rate is not None and not Decimal(0) <= factoring_rate <= Decimal(1):
            raise DomainValidationError("factoring_rate must be a fraction between 0 and 1")

        assumptions: list[str] = []
        missing: list[str] = []

        total_miles = self._total_miles(loaded_miles, empty_miles, missing)

        fuel_price = (
            fuel_price_per_gallon
            if fuel_price_per_gallon is not None
            else vehicle.fuel_price_per_gallon
        )
        fuel: Money | None = None
        if fuel_price is None:
            missing.append("fuel_price_per_gallon")
        elif total_miles is not None:
            fuel = Money(amount=total_miles.miles / vehicle.fuel_efficiency_mpg * fuel_price.amount)

        policy = driver_pay if driver_pay is not None else vehicle.driver_pay
        driver: Money | None = None
        if policy is None:
            missing.append("driver_pay")
        else:
            driver = policy.amount_for(
                gross_revenue=price_offered,
                total_miles=total_miles,
                loaded_miles=loaded_miles,
                duration=duration,
            )
            if isinstance(policy, DriverPayByMile):
                assumptions.append(
                    DRIVER_PAY_TOTAL_MILES
                    if policy.mile_basis == "total"
                    else DRIVER_PAY_LOADED_MILES
                )
            if isinstance(policy, DriverPayHourly) and duration is None:
                missing.append("duration")

        factoring: Money | None = None
        if factoring_rate is None:
            missing.append("factoring_rate")
        else:
            factoring = Money(amount=price_offered.amount * factoring_rate)

        tolls_cost = tolls
        if tolls_cost is None:
            if vehicle.tolls_per_mile is None:
                missing.append("tolls")
            elif total_miles is not None:
                tolls_cost = Money(amount=vehicle.tolls_per_mile.amount * total_miles.miles)
                assumptions.append(TOLLS_FROM_RATE)

        operational: Money | None = None
        if vehicle.operating_cost_per_mile is None:
            missing.append("operating_cost_per_mile")
        elif total_miles is not None:
            operational = Money(amount=vehicle.operating_cost_per_mile.amount * total_miles.miles)

        if other_costs is None:
            other = Money(amount=Decimal(0))
            assumptions.append(OTHER_COSTS_ASSUMED_ZERO)
        else:
            other = other_costs

        if vehicle.fixed_cost_per_month is not None:
            assumptions.append(FIXED_COST_NOT_ALLOCATED)

        components: tuple[Money | None, ...] = (
            fuel,
            driver,
            factoring,
            tolls_cost,
            operational,
            other,
        )
        total_costs = (
            Money(amount=sum(component.amount for component in components if component is not None))
            if all(component is not None for component in components)
            else None
        )

        net_profit = (
            Money(amount=price_offered.amount - total_costs.amount)
            if total_costs is not None
            else None
        )

        gross_rpm, net_rpm = self._rates_per_mile(
            price_offered=price_offered,
            net_profit=net_profit,
            total_miles=total_miles,
            missing=missing,
        )
        profit_per_hour = self._profit_per_hour(
            net_profit=net_profit, duration=duration, missing=missing
        )

        costs = CostBreakdown(
            fuel=fuel,
            driver=driver,
            factoring=factoring,
            tolls=tolls_cost,
            operational=operational,
            other=other,
            total=total_costs,
        )
        profitability = Profitability(
            gross_revenue=price_offered,
            total_costs=total_costs,
            net_profit=net_profit,
            gross_rpm=gross_rpm,
            net_rpm=net_rpm,
            profit_per_hour=profit_per_hour,
            is_complete=all(
                metric is not None for metric in (net_profit, gross_rpm, net_rpm, profit_per_hour)
            ),
            missing_inputs=_unique(missing),
        )
        return FinancialEstimate(
            costs=costs,
            profitability=profitability,
            assumptions=tuple(dict.fromkeys(assumptions)),
        )

    @staticmethod
    def _total_miles(
        loaded_miles: Distance | None,
        empty_miles: Distance | None,
        missing: list[str],
    ) -> Distance | None:
        if loaded_miles is None:
            missing.append("loaded_miles")
        if empty_miles is None:
            missing.append("empty_miles")
        if loaded_miles is None or empty_miles is None:
            return None
        return Distance(miles=loaded_miles.miles + empty_miles.miles)

    @staticmethod
    def _rates_per_mile(
        *,
        price_offered: Money,
        net_profit: Money | None,
        total_miles: Distance | None,
        missing: list[str],
    ) -> tuple[RatePerMile | None, RatePerMile | None]:
        if total_miles is None:
            return None, None
        if total_miles.miles == 0:
            missing.append("total_miles")
            return None, None

        gross_rpm = RatePerMile(amount=price_offered.amount / total_miles.miles)
        net_rpm = (
            RatePerMile(amount=net_profit.amount / total_miles.miles)
            if net_profit is not None
            else None
        )
        return gross_rpm, net_rpm

    @staticmethod
    def _profit_per_hour(
        *,
        net_profit: Money | None,
        duration: Duration | None,
        missing: list[str],
    ) -> RatePerHour | None:
        if duration is None:
            missing.append("duration")
            return None
        if duration.hours == 0:
            missing.append("duration")
            return None
        if net_profit is None:
            return None
        return RatePerHour(amount=net_profit.amount / duration.hours)
