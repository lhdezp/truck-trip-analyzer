"""Vehicle profile entity."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import Field, field_validator

from app.domain.base import Entity
from app.domain.value_objects.dimensions import Dimensions
from app.domain.value_objects.driver_pay import DriverPayPolicy
from app.domain.value_objects.equipment import EquipmentType
from app.domain.value_objects.money import Money
from app.domain.value_objects.weight import Weight


class VehicleProfile(Entity):
    """A truck the user actually operates.

    The profile holds *operational facts*: what the vehicle is, what it can carry and
    what it costs to run. Driver pay is a policy and lives in ``driver_pay`` with an
    explicit strategy; factoring rate and deadhead assumptions stay out of the profile
    because they describe a deal or a business setting, not a vehicle.
    """

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=80)
    equipment_type: EquipmentType

    max_payload: Weight | None = None
    interior_dimensions: Dimensions | None = None

    fuel_efficiency_mpg: Decimal = Field(gt=0)
    fuel_price_per_gallon: Money | None = None

    operating_cost_per_mile: Money | None = None
    driver_pay: DriverPayPolicy | None = None
    tolls_per_mile: Money | None = None
    fixed_cost_per_month: Money | None = None

    restrictions: tuple[str, ...] = ()
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _normalise_name(cls, value: str) -> str:
        normalised = " ".join(value.split())
        if not normalised:
            raise ValueError("name must not be blank")
        return normalised
