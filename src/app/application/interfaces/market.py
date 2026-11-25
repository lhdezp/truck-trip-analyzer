"""Market data port."""

from __future__ import annotations

from typing import Protocol

from app.application.schemas.analysis import MarketReference
from app.domain.value_objects.equipment import EquipmentType
from app.domain.value_objects.location import USLocation


class MarketDataProvider(Protocol):
    """Returns references the analysis can compare against.

    Implementations must return only references whose equipment category and
    geographic scope are explicit. Returning dry van rates for a box truck query is a
    contract violation, not a fallback. An empty list means "no comparable data", a
    valid and expected answer.
    """

    async def fetch_market_references(
        self,
        *,
        equipment: EquipmentType,
        origin: USLocation,
        destination: USLocation,
    ) -> list[MarketReference]: ...
