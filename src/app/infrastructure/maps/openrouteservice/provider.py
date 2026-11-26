"""OpenRouteService routing adapter.

Computes distance and duration between two US locations using the HeiGIT-hosted
endpoints:

- geocoding: ``GET /pelias/v1/search`` (Pelias, GeoJSON ``features``);
- directions: ``POST /openrouteservice/v2/directions/driving-car/geojson``.

The legacy host ``api.openrouteservice.org`` was deprecated on 2026-04-28 and stopped
answering on 2026-11-24 with ``410 Gone``; every call here targets its replacement,
``api.heigit.org``. A geocoding miss is reported as a limitation, while a transport or
server failure raises :class:`~app.exceptions.ProviderError` so the analysis can name
the gap instead of silently losing the distance.

Only the driving profile is used: box trucks are not a separate profile, and the
result is a plain driving distance, not a truck-legally-constrained route.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import httpx

from app.application.schemas.analysis import RouteAnalysis
from app.application.schemas.routing import RouteRequest
from app.config import Settings
from app.domain.value_objects.distance import Distance, Duration
from app.domain.value_objects.location import USLocation
from app.exceptions import (
    PROVIDER_KIND_REJECTED,
    PROVIDER_KIND_UNAUTHORIZED,
    PROVIDER_KIND_UNAVAILABLE,
    ConfigurationError,
    ProviderError,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME = "openrouteservice"
_USER_AGENT = "truck-load-analyzer/0.1 (+https://github.com/truck-load-analyzer)"

_BASE_URL = "https://api.heigit.org"
_GEOCODE_PATH = "/pelias/v1/search"
_PROFILE = "driving-car"
_DIRECTIONS_PATH = f"/openrouteservice/v2/directions/{_PROFILE}/geojson"

_METRES_PER_MILE = Decimal("1609.344")
_SECONDS_PER_HOUR = Decimal("3600")


def _snippet(text: str, *, limit: int = 200) -> str:
    """One-line, bounded rendering of a vendor body for the log."""
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else f"{collapsed[: limit - 1]}…"


def _kind_for_status(status: int) -> str:
    """Map an HTTP status to the shared provider failure categories."""
    if status in (401, 403):
        return PROVIDER_KIND_UNAUTHORIZED
    if status == 429 or status >= 500:
        return PROVIDER_KIND_UNAVAILABLE
    return PROVIDER_KIND_REJECTED


def _summary_value(props: dict[str, object], key: str) -> float | None:
    """Read a metric from ``properties.summary``, falling back to ``properties``.

    The GeoJSON answer nests ``distance`` and ``duration`` under ``summary``; older
    responses put them at the top level, so both shapes are accepted.
    """
    for source in (props.get("summary"), props):
        if isinstance(source, dict):
            value = source.get(key)
            if isinstance(value, int | float) and not isinstance(value, bool):
                return float(value)
    return None


class OpenRouteServiceClient:
    """HTTP client for the HeiGIT-hosted OpenRouteService API."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        key = (
            settings.OPENROUTESERVICE_API_KEY.get_secret_value().strip()
            if settings.OPENROUTESERVICE_API_KEY is not None
            else ""
        )
        if not key:
            raise ConfigurationError(
                "OPENROUTESERVICE_API_KEY is required to start the routing adapter"
            )

        headers = {
            "Authorization": key,
            "User-Agent": _USER_AGENT,
            "Accept": "application/geo+json",
        }
        self._client = client or httpx.AsyncClient(
            base_url=_BASE_URL, headers=headers, timeout=30.0
        )
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def geocode(self, query: str) -> tuple[float, float] | None:
        """Resolve a free-text US place to ``(lon, lat)``, or ``None`` when unknown.

        A miss (no result, unparsable answer) is not an outage: the caller reports it
        as a limitation. Only transport and server failures raise.
        """
        try:
            response = await self._client.get(
                _GEOCODE_PATH,
                params={"text": query, "size": 1, "boundary.country": "US"},
            )
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"OpenRouteService geocoding request failed: {type(exc).__name__}",
                provider=PROVIDER_NAME,
                details={"kind": PROVIDER_KIND_UNAVAILABLE, "query": query},
            ) from exc

        if response.status_code >= 400:
            logger.warning(
                "OpenRouteService geocoding returned %s for %r: %s",
                response.status_code,
                query,
                _snippet(response.text),
            )
            return None

        return _first_coordinate(response.json())

    async def directions(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
    ) -> dict[str, object]:
        """Fetch the driving route between two ``(lon, lat)`` pairs."""
        payload = {"coordinates": [list(origin), list(destination)]}
        try:
            response = await self._client.post(_DIRECTIONS_PATH, json=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"OpenRouteService directions request failed: {type(exc).__name__}",
                provider=PROVIDER_NAME,
                details={"kind": PROVIDER_KIND_UNAVAILABLE},
            ) from exc

        if response.status_code >= 400:
            raise ProviderError(
                f"OpenRouteService directions returned {response.status_code}: "
                f"{_snippet(response.text)}",
                provider=PROVIDER_NAME,
                details={
                    "kind": _kind_for_status(response.status_code),
                    "status_code": response.status_code,
                },
            )
        data: dict[str, object] = response.json()
        return data


def _first_coordinate(payload: object) -> tuple[float, float] | None:
    """Extract ``(lon, lat)`` from a Pelias GeoJSON answer."""
    if not isinstance(payload, dict):
        return None
    features = payload.get("features")
    if not isinstance(features, list) or not features:
        return None
    feature = features[0]
    if not isinstance(feature, dict):
        return None
    geometry = feature.get("geometry")
    coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None
    lon, lat = coordinates[0], coordinates[1]
    if not isinstance(lon, int | float) or not isinstance(lat, int | float):
        return None
    properties = feature.get("properties")
    if isinstance(properties, dict):
        logger.debug(
            "Geocoded to %r (confidence %s)", properties.get("label"), properties.get("confidence")
        )
    return (float(lon), float(lat))


class OpenRouteServiceRoutingProvider:
    """Answers the :class:`RoutingProvider` port using OpenRouteService."""

    name: str = PROVIDER_NAME

    def __init__(self, client: OpenRouteServiceClient) -> None:
        self._client = client

    async def analyze_route(self, request: RouteRequest) -> RouteAnalysis:
        """Compute distance and duration for the route.

        OpenRouteService needs lon/lat, but the domain only has city/state. This
        adapter geocodes both ends first; a location that cannot be resolved becomes a
        limitation, not a crash.
        """
        origin_ll = await self._geocode(request.origin)
        destination_ll = await self._geocode(request.destination)
        if origin_ll is None or destination_ll is None:
            return RouteAnalysis(
                origin=request.origin,
                destination=request.destination,
                limitations=["geocoding failed for one or both locations"],
            )

        data = await self._client.directions(origin_ll, destination_ll)
        props = _first_properties(data)
        if props is None:
            return RouteAnalysis(
                origin=request.origin,
                destination=request.destination,
                limitations=["no route found between the two locations"],
            )

        distance_m = _summary_value(props, "distance")
        duration_s = _summary_value(props, "duration")
        if distance_m is None or duration_s is None:
            return RouteAnalysis(
                origin=request.origin,
                destination=request.destination,
                limitations=["the route response carried no distance or duration"],
            )

        distance_mi = Decimal(str(distance_m)) / _METRES_PER_MILE
        duration_h = Decimal(str(duration_s)) / _SECONDS_PER_HOUR

        limitations: list[str] = []
        if request.vehicle is not None:
            limitations.append(
                "Route computed with the car profile; HOS and truck restrictions were not checked"
            )

        return RouteAnalysis(
            origin=request.origin,
            destination=request.destination,
            loaded_miles=Distance(miles=distance_mi),
            empty_miles=Distance(miles=Decimal(0)),
            total_miles=Distance(miles=distance_mi),
            duration=Duration(hours=duration_h),
            provider=PROVIDER_NAME,
            routing_profile=_PROFILE,
            limitations=limitations,
        )

    async def _geocode(self, location: USLocation) -> tuple[float, float] | None:
        """Resolve a USLocation to lon/lat via the provider's geocoder."""
        query = f"{location.city}, {location.state}"
        if location.postal_code:
            query += f" {location.postal_code}"
        point = await self._client.geocode(query)
        if point is None:
            logger.info("OpenRouteService could not geocode %r", query)
        return point


def _first_properties(data: dict[str, object]) -> dict[str, object] | None:
    """Return the properties of the first GeoJSON feature, or ``None``."""
    features = data.get("features")
    if not isinstance(features, list) or not features:
        return None
    feature = features[0]
    if not isinstance(feature, dict):
        return None
    props = feature.get("properties")
    return props if isinstance(props, dict) else None
