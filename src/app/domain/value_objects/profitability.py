"""Profitability metrics."""

from __future__ import annotations

from pydantic import model_validator

from app.domain.base import ValueObject
from app.domain.value_objects.costs import CostBreakdown
from app.domain.value_objects.money import Money, RatePerHour, RatePerMile


class Profitability(ValueObject):
    """Revenue, cost and efficiency metrics for one load.

    ``is_complete`` means every headline metric could be computed. Missing inputs are
    named explicitly so the analysis can explain *why* a number is absent instead of
    showing a misleading zero.
    """

    gross_revenue: Money | None = None
    total_costs: Money | None = None
    net_profit: Money | None = None
    gross_rpm: RatePerMile | None = None
    net_rpm: RatePerMile | None = None
    profit_per_hour: RatePerHour | None = None
    is_complete: bool = False
    missing_inputs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _profit_must_match_revenue_minus_cost(self) -> Profitability:
        if self.gross_revenue and self.total_costs and self.net_profit:
            expected = self.gross_revenue.amount - self.total_costs.amount
            if self.net_profit.amount != expected:
                raise ValueError(
                    "net_profit must equal gross_revenue - total_costs "
                    f"(expected {expected}, got {self.net_profit.amount})"
                )
        return self


class FinancialEstimate(ValueObject):
    """Everything the engine returns: numbers plus the assumptions behind them."""

    costs: CostBreakdown
    profitability: Profitability
    assumptions: tuple[str, ...] = ()
