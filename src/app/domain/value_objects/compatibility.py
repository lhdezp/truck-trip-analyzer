"""Vehicle compatibility result."""

from __future__ import annotations

from pydantic import Field

from app.domain.base import ValueObject


class VehicleCompatibility(ValueObject):
    """Whether the selected vehicle can take the load.

    ``None`` means "cannot be determined with the available data". It is never used
    as a synonym for ``False`` ("determined to be incompatible").
    """

    compatible: bool | None = None
    equipment_match: bool | None = None
    payload_ok: bool | None = None
    dimensions_ok: bool | None = None
    issues: tuple[str, ...] = Field(default_factory=tuple)
