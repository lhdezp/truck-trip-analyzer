"""OpenRouteService routing adapter.

Computes distance and duration between two US locations using the free
``/v1/geocode`` + ``/v2/directions/driving-traffic/geojson`` endpoints. The adapter
sends an explicit ``User-Agent`` (OpenRouteService rejects default script agents) and
translates vendor failures to :class:`~app.exceptions.ProviderError`.

Only the driving profile is used: box trucks are not a separate profile, and the
result is a plain driving distance, not a truck-legally-constrained route.
"""

from __future__ import annotations

from decimal import Decimal

import httpx

from app.application.schemas.analysis import RouteAnalysis
from app.application.schemas.routing import RouteRequest
from app.config import Settings
from app.domain.value_objects.distance import Distance, Duration
from app.domain.value_objects.location import USLocation
from app.exceptions import ConfigurationError, ProviderError

PROVIDER_NAME = "openrouteservice"
_USER_AGENT = "truck-load-analyzer/0.1 (+https://github.com/truck-load-analyzer)"


class OpenRouteServiceClient:
    """HTTP client for OpenRouteService."""

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

        base_url = "https://api.openrouteservice.org"
        headers = {
            "Authorization": f"Bearer {key}",
            "User-Agent": _USER_AGENT,
            "Accept": "application/geo+json",
        }
        self._client = client or httpx.AsyncClient(base_url=base_url, headers=headers, timeout=30.0)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get_directions(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
    ) -> dict[str, object]:
        """Fetch driving directions between two lon/lat pairs.

        Returns the GeoJSON features list from the API response.
        """
        payload = {
            "coordinates": [list(origin), list(destination)],
            "profile": "car",
        }
        try:
            response = await self._client.post("/v2/directions/car/geojson", json=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"OpenRouteService request failed: {exc}",
                provider=PROVIDER_NAME,
            ) from exc
        if response.status_code >= 400:
            raise ProviderError(
                f"OpenRouteService returned {response.status_code}: {response.text[:200]}",
                provider=PROVIDER_NAME,
            )
        data: dict[str, object] = response.json()
        return data


class OpenRouteServiceRoutingProvider:
    """Answers the :class:`RoutingProvider` port using OpenRouteService."""

    name: str = PROVIDER_NAME

    def __init__(self, client: OpenRouteServiceClient) -> None:
        self._client = client

    async def analyze_route(self, request: RouteRequest) -> RouteAnalysis:
        """Compute distance and duration for the route.

        OpenRouteService needs lon/lat, but the domain only has city/state. This
        adapter geocodes the locations via the provider's geocoding endpoint before
        requesting directions.
        """
        origin_ll = await self._geocode(request.origin)
        destination_ll = await self._geocode(request.destination)
        if origin_ll is None or destination_ll is None:
            return RouteAnalysis(
                origin=request.origin,
                destination=request.destination,
                limitations=["geocoding failed for one or both locations"],
            )

        data = await self._client._get_directions(origin_ll, destination_ll)
        features_raw = data.get("features", [])
        if not isinstance(features_raw, list) or not features_raw:
            return RouteAnalysis(
                origin=request.origin,
                destination=request.destination,
                limitations=["no route found between the two locations"],
            )
        first_feature = features_raw[0]
        if not isinstance(first_feature, dict):
            return RouteAnalysis(
                origin=request.origin,
                destination=request.destination,
                limitations=["no route found between the two locations"],
            )
        props_raw = first_feature.get("properties", {})
        props = props_raw if isinstance(props_raw, dict) else {}

        # OpenRouteService returns distance in metres, duration in seconds.
        distance_m = props.get("distance", 0.0)
        duration_s = props.get("duration", 0.0)
        distance_mi = Decimal(str(distance_m / 1609.344))
        duration_h = Decimal(str(duration_s / 3600))

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
            routing_profile="car",
            limitations=limitations,
        )

    async def _geocode(self, location: USLocation) -> tuple[float, float] | None:
        """Resolve a USLocation to lon/lat via OpenRouteService's geocoder.

        Returns ``None`` when the location cannot be resolved; the caller reports
        the gap in ``limitations`` instead of raising.
        """
        query = f"{location.city}, {location.state}"
        if location.postal_code:
            query += f" {location.postal_code}"
        try:
            response = await self._client._client.get(
                "/v2/geocode",
                params={"profile": "amap", "text": query, "count": 1},
            )
        except httpx.HTTPError:
            return None
        if response.status_code >= 400:
            return None
        data = response.json()
        results = data.get("results", [])
        if not results:
            return None
        location_obj = results[0].get("location")
        if not location_obj:
            return None
        return (float(location_obj[0]), float(location_obj[1]))
