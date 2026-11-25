"""Route request contract."""

from __future__ import annotations

from app.application.schemas.base import Schema
from app.domain.entities.vehicle import VehicleProfile
from app.domain.value_objects.location import USLocation


class RouteRequest(Schema):
    """Input for a routing provider.

    The vehicle is optional because distance can be computed without it, and the
    provider may not support every restriction the vehicle implies.
    """

    origin: USLocation
    destination: USLocation
    vehicle: VehicleProfile | None = None
