"""Preliminary decision rules.

Thresholds are business policy supplied by the caller; the rules only compare verified
numbers against them. No scoring, no weighting, no fabricated confidence.
"""

from __future__ import annotations

from app.domain.base import ValueObject
from app.domain.value_objects.money import Money, RatePerHour, RatePerMile
from app.domain.value_objects.profitability import Profitability
from app.domain.value_objects.provenance import ConfidenceLevel
from app.domain.value_objects.recommendation import FinalRecommendation, RecommendationDecision


class ProfitThresholds(ValueObject):
    """Minimum acceptable outcome for the operator.

    ``target_price`` and ``break_even_price`` are derived from real costs, not from
    market guesses: the break-even price is the total cost of running the trip.
    """

    minimum_net_profit: Money
    minimum_net_rpm: RatePerMile
    minimum_profit_per_hour: RatePerHour | None = None

    def break_even_price(self, total_costs: Money) -> Money:
        """Offered price at which net profit is exactly zero."""
        return total_costs

    def target_price(self, total_costs: Money) -> Money:
        """Offered price that reaches the minimum net profit."""
        return Money(amount=total_costs.amount + self.minimum_net_profit.amount)


def evaluate_recommendation(
    *,
    profitability: Profitability,
    thresholds: ProfitThresholds,
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN,
) -> FinalRecommendation:
    """Turn profitability into ACCEPT / NEGOTIATE / REJECT / INSUFFICIENT_DATA.

    Rules, in order:

    1. Missing net profit or net RPM → ``INSUFFICIENT_DATA``.
    2. Negative net profit or net RPM → ``REJECT``: negotiating a loss-making trip is
       not a price problem, it is a trip that does not pay for itself.
    3. All thresholds met → ``ACCEPT``.
    4. Otherwise → ``NEGOTIATE``, naming the gap.
    """
    net_profit = profitability.net_profit
    net_rpm = profitability.net_rpm

    if net_profit is None or net_rpm is None:
        missing = ", ".join(profitability.missing_inputs) or "net profit and net RPM"
        return FinalRecommendation(
            decision=RecommendationDecision.INSUFFICIENT_DATA,
            reasons=(f"Cannot evaluate profitability without: {missing}",),
            confidence=ConfidenceLevel.LOW,
        )

    if net_profit.amount < 0 or net_rpm.amount < 0:
        return FinalRecommendation(
            decision=RecommendationDecision.REJECT,
            reasons=(
                f"Trip loses money: net profit {net_profit} at {net_rpm}",
                "A loss cannot be fixed by negotiating a few cents; costs exceed revenue",
            ),
            confidence=confidence,
        )

    reasons: list[str] = []
    below_threshold = False

    if net_profit.amount < thresholds.minimum_net_profit.amount:
        below_threshold = True
        reasons.append(
            f"Net profit {net_profit} is below the minimum of {thresholds.minimum_net_profit}"
        )
    else:
        reasons.append(
            f"Net profit {net_profit} meets the minimum of {thresholds.minimum_net_profit}"
        )

    if net_rpm.amount < thresholds.minimum_net_rpm.amount:
        below_threshold = True
        reasons.append(f"Net RPM {net_rpm} is below the minimum of {thresholds.minimum_net_rpm}")
    else:
        reasons.append(f"Net RPM {net_rpm} meets the minimum of {thresholds.minimum_net_rpm}")

    if thresholds.minimum_profit_per_hour is not None:
        per_hour = profitability.profit_per_hour
        if per_hour is None:
            below_threshold = True
            reasons.append("Profit per hour is unknown, so the hourly threshold cannot be met")
        elif per_hour.amount < thresholds.minimum_profit_per_hour.amount:
            below_threshold = True
            reasons.append(
                f"Profit per hour {per_hour} is below the minimum of "
                f"{thresholds.minimum_profit_per_hour}"
            )
        else:
            reasons.append(
                f"Profit per hour {per_hour} meets the minimum of "
                f"{thresholds.minimum_profit_per_hour}"
            )

    if below_threshold:
        return FinalRecommendation(
            decision=RecommendationDecision.NEGOTIATE,
            reasons=tuple(reasons),
            confidence=confidence,
        )
    return FinalRecommendation(
        decision=RecommendationDecision.ACCEPT,
        reasons=tuple(reasons),
        confidence=confidence,
    )
