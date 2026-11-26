"""OpenRouteService adapter against the HeiGIT endpoints.

The legacy host stopped answering on 2026-11-24 with ``410 Gone``, so these tests pin
the paths, the profile name and the response shape that actually work today. They use
``httpx.MockTransport``: no network, no key.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.application.schemas.routing import RouteRequest
from app.config import Settings
from app.domain.value_objects.location import USLocation
from app.exceptions import PROVIDER_KIND_UNAVAILABLE, ProviderError
from app.infrastructure.maps.openrouteservice.provider import (
    OpenRouteServiceClient,
    OpenRouteServiceRoutingProvider,
)

BASE = "https://api.heigit.org"
STRAFFORD = USLocation(city="Strafford", state="MO", postal_code="65757")
PIEDMONT = USLocation(city="Piedmont", state="CA", postal_code="94611")

_PELIAS = {
    "geocoding": {"version": "0.2"},
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-93.118724, 37.268439]},
            "properties": {"label": "Strafford, MO, USA", "confidence": 0.6},
        }
    ],
}

_DIRECTIONS = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": []},
            "properties": {
                "summary": {"distance": 3001.5 * 1609.344, "duration": 46.2 * 3600},
                "segments": [],
            },
        }
    ],
}


def _client(handler: Any) -> OpenRouteServiceClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(
        base_url=BASE,
        transport=transport,
        headers={"Authorization": "test-key"},
    )
    settings = Settings(_env_file=None, OPENROUTESERVICE_API_KEY="test-key")
    return OpenRouteServiceClient(settings, client=http)


def _request() -> RouteRequest:
    return RouteRequest(origin=STRAFFORD, destination=PIEDMONT)


async def test_route_uses_pelias_geocoding_and_driving_car_directions() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/pelias/v1/search":
            assert request.url.params["boundary.country"] == "US"
            assert request.url.params["size"] == "1"
            return httpx.Response(200, json=_PELIAS)
        if request.url.path == "/openrouteservice/v2/directions/driving-car/geojson":
            return httpx.Response(200, json=_DIRECTIONS)
        return httpx.Response(404, json={"error": "unexpected path"})

    provider = OpenRouteServiceRoutingProvider(_client(handler))
    route = await provider.analyze_route(_request())

    assert ("GET", "/pelias/v1/search") in seen
    assert ("POST", "/openrouteservice/v2/directions/driving-car/geojson") in seen
    assert route.loaded_miles is not None
    assert abs(float(route.loaded_miles.miles) - 3001.5) < 0.5
    assert route.duration is not None
    assert abs(float(route.duration.hours) - 46.2) < 0.5
    assert route.routing_profile == "driving-car"
    assert route.limitations == []


async def test_legacy_top_level_metrics_are_still_accepted() -> None:
    payload = {
        "features": [
            {"properties": {"distance": 1609.344, "duration": 3600.0}},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/pelias/v1/search":
            return httpx.Response(200, json=_PELIAS)
        return httpx.Response(200, json=payload)

    route = await OpenRouteServiceRoutingProvider(_client(handler)).analyze_route(_request())

    assert route.loaded_miles is not None
    assert float(route.loaded_miles.miles) == pytest.approx(1.0)
    assert route.duration is not None
    assert float(route.duration.hours) == pytest.approx(1.0)


async def test_geocoding_miss_is_a_limitation_not_a_crash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/pelias/v1/search":
            return httpx.Response(410, text="Deprecated HeiGIT API URL")
        return httpx.Response(200, json=_DIRECTIONS)

    route = await OpenRouteServiceRoutingProvider(_client(handler)).analyze_route(_request())

    assert route.loaded_miles is None
    assert route.limitations == ["geocoding failed for one or both locations"]


async def test_directions_outage_raises_a_classified_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/pelias/v1/search":
            return httpx.Response(200, json=_PELIAS)
        return httpx.Response(503, text="upstream unavailable")

    provider = OpenRouteServiceRoutingProvider(_client(handler))

    with pytest.raises(ProviderError) as raised:
        await provider.analyze_route(_request())

    assert raised.value.kind == PROVIDER_KIND_UNAVAILABLE
    assert raised.value.details["status_code"] == 503
