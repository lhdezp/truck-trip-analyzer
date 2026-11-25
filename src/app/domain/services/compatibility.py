"""Vehicle and load compatibility.

Conservative by design: the engine never assumes one equipment type can substitute for
another. A straight truck is not automatically acceptable for a box truck load; that
is a decision for the operator, not a silent equivalence in code.
"""

from __future__ import annotations

from app.domain.entities.load import LoadOffer
from app.domain.entities.vehicle import VehicleProfile
from app.domain.value_objects.compatibility import VehicleCompatibility


def check_vehicle_compatibility(
    *,
    load: LoadOffer,
    vehicle: VehicleProfile,
) -> VehicleCompatibility:
    """Compare a load against a vehicle profile.

    Returns ``compatible=None`` when no check failed but some check could not be
    performed, so "unknown" never masquerades as "approved".
    """
    issues: list[str] = []
    checks: list[bool | None] = []

    equipment_match: bool | None = None
    if load.required_equipment is not None:
        required = load.required_equipment.value
        equipment_match = required is vehicle.equipment_type
        if not equipment_match:
            issues.append(
                f"Load requires {required.value}, vehicle is {vehicle.equipment_type.value}"
            )
        checks.append(equipment_match)

    payload_ok: bool | None = None
    if load.weight is not None and vehicle.max_payload is not None:
        payload_ok = load.weight.value.pounds <= vehicle.max_payload.pounds
        if not payload_ok:
            issues.append(f"Load weight {load.weight.value} exceeds payload {vehicle.max_payload}")
        checks.append(payload_ok)

    dimensions_ok: bool | None = None
    if load.dimensions is not None and vehicle.interior_dimensions is not None:
        cargo = load.dimensions.value
        interior = vehicle.interior_dimensions
        dimensions_ok = (
            cargo.length_in <= interior.length_in
            and cargo.width_in <= interior.width_in
            and cargo.height_in <= interior.height_in
        )
        if not dimensions_ok:
            issues.append("Cargo dimensions exceed the available interior space")
        checks.append(dimensions_ok)

    if any(check is False for check in checks):
        compatible: bool | None = False
    elif checks and all(check is True for check in checks):
        compatible = True
    else:
        compatible = None
        if not checks:
            issues.append("No compatibility check could be performed with the available data")

    return VehicleCompatibility(
        compatible=compatible,
        equipment_match=equipment_match,
        payload_ok=payload_ok,
        dimensions_ok=dimensions_ok,
        issues=tuple(issues),
    )
