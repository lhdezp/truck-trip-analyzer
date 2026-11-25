"""Equipment types.

The list separates straight-truck family vehicles from trailer-based equipment on
purpose: market data for dry van, reefer or flatbed is not comparable with a box
truck, and the model must not make that mistake easy.
"""

from __future__ import annotations

from enum import StrEnum


class EquipmentType(StrEnum):
    """Vehicle or trailer category required by a load."""

    BOX_TRUCK = "box_truck"
    STRAIGHT_TRUCK = "straight_truck"
    CARGO_VAN = "cargo_van"
    DRY_VAN = "dry_van"
    REEFER = "reefer"
    FLATBED = "flatbed"
    OTHER = "other"

    @property
    def is_straight_truck_family(self) -> bool:
        """True for vehicles whose cargo box is part of the vehicle itself."""
        return self in {
            EquipmentType.BOX_TRUCK,
            EquipmentType.STRAIGHT_TRUCK,
            EquipmentType.CARGO_VAN,
        }
