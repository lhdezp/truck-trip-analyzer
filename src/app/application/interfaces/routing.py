"""Routing port."""

from __future__ import annotations

from typing import Protocol

from app.application.schemas.analysis import RouteAnalysis
from app.application.schemas.routing import RouteRequest


class RoutingProvider(Protocol):
    """Computes distance and duration between two US locations.

    Implementations must fill ``limitations`` with what they could not verify: a
    calculated route is not proof that every legal restriction for the vehicle was
    checked.
    """

    async def analyze_route(self, request: RouteRequest) -> RouteAnalysis: ...
