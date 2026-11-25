"""Load offer entity."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from app.domain.base import Entity
from app.domain.value_objects.dimensions import Dimensions
from app.domain.value_objects.distance import Distance
from app.domain.value_objects.equipment import EquipmentType
from app.domain.value_objects.location import USLocation
from app.domain.value_objects.money import Money
from app.domain.value_objects.provenance import SourcedField
from app.domain.value_objects.time_window import TimeWindow
from app.domain.value_objects.weight import Weight

Pieces = Annotated[int, Field(ge=1)]


class LoadField(StrEnum):
    """Every field of a load offer, named for reporting in ``missing_fields``."""

    BROKER = "broker"
    REFERENCE_NUMBER = "reference_number"
    ORIGIN = "origin"
    DESTINATION = "destination"
    ANNOUNCED_DISTANCE = "announced_distance"
    PRICE_OFFERED = "price_offered"
    COMMODITY = "commodity"
    WEIGHT = "weight"
    PIECES = "pieces"
    DIMENSIONS = "dimensions"
    PICKUP_WINDOW = "pickup_window"
    DELIVERY_WINDOW = "delivery_window"
    REQUIRED_EQUIPMENT = "required_equipment"
    SPECIAL_REQUIREMENTS = "special_requirements"
    NOTES = "notes"


class LoadOffer(Entity):
    """A freight offer as extracted or entered by the user.

    Every field is optional and carries provenance. ``None`` means the value is
    unknown; a present field may legitimately hold a zero amount. The entity stores no
    opinion about profitability: that belongs to the financial engine.
    """

    broker: SourcedField[str] | None = None
    reference_number: SourcedField[str] | None = None
    origin: SourcedField[USLocation] | None = None
    destination: SourcedField[USLocation] | None = None
    announced_distance: SourcedField[Distance] | None = None
    price_offered: SourcedField[Money] | None = None
    commodity: SourcedField[str] | None = None
    weight: SourcedField[Weight] | None = None
    pieces: SourcedField[Pieces] | None = None
    dimensions: SourcedField[Dimensions] | None = None
    pickup_window: SourcedField[TimeWindow] | None = None
    delivery_window: SourcedField[TimeWindow] | None = None
    required_equipment: SourcedField[EquipmentType] | None = None
    special_requirements: SourcedField[tuple[str, ...]] | None = None
    notes: SourcedField[str] | None = None

    def missing_fields(self) -> list[LoadField]:
        """Fields without which no financial analysis can be produced.

        Only the minimum set is listed. Missing weight or dimensions degrade the
        vehicle compatibility check, but do not block a cost estimate.
        """
        missing: list[LoadField] = []
        if self.origin is None:
            missing.append(LoadField.ORIGIN)
        if self.destination is None:
            missing.append(LoadField.DESTINATION)
        if self.price_offered is None:
            missing.append(LoadField.PRICE_OFFERED)
        return missing

    @property
    def is_financially_analyzable(self) -> bool:
        """True when origin, destination and offered price are all known."""
        return not self.missing_fields()
