"""Cost breakdown produced by the financial engine."""

from __future__ import annotations

from app.domain.base import ValueObject
from app.domain.value_objects.money import Money


class CostBreakdown(ValueObject):
    """Money spent on the trip.

    A component is ``None`` when it could not be computed. ``total`` is ``None``
    whenever any component is unknown: summing a partial breakdown would understate
    cost and overstate profit.
    """

    fuel: Money | None = None
    driver: Money | None = None
    factoring: Money | None = None
    tolls: Money | None = None
    operational: Money | None = None
    other: Money | None = None
    total: Money | None = None
