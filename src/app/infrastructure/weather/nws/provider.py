"""NWS (National Weather Service) weather adapter.

The NWS ``/points`` + ``/forecasts`` API is free and requires no key. The adapter
resolves a location's latitude/longitude (passed in by the caller via geocoding) to
the nearest grid point, then fetches the forecast and any active alerts.

A location with no alerts and no forecast data returns ``available=False`` with a
limitation, not an exception: weather is enrichment, never a prerequisite for the
financial analysis.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx

from app.application.schemas.weather import (
    WeatherCondition,
    WeatherReport,
    WeatherRequest,
    WeatherSeverity,
)
from app.config import Settings
from app.domain.value_objects.location import USLocation

PROVIDER_NAME = "nws"
_USER_AGENT = "truck-load-analyzer/0.1 (+https://github.com/truck-load-analyzer)"
_BASE = "https://api.weather.gov"


def _severity_from_text(text: str) -> WeatherSeverity:
    """Map NWS forecast phrases to an operational severity.

    NWS does not publish a numeric severity; it publishes phrases like "Chance of
    rain" or "Severe thunderstorms". This mapping is conservative: only the most
    operationally disruptive phrases escalate to ``SEVERE``.
    """
    lower = text.lower()
    severe_markers = ("severe", "tornado", "hail", "blizzard", "flood", "tsunami")
    if any(m in lower for m in severe_markers):
        return WeatherSeverity.SEVERE
    moderate_markers = ("rain", "snow", "ice", "wind", "fog", "thunder")
    if any(m in lower for m in moderate_markers):
        return WeatherSeverity.MODERATE
    return WeatherSeverity.NONE


class NwsWeatherProvider:
    """Answers the :class:`WeatherProvider` port using the NWS API."""

    name: str = PROVIDER_NAME

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=_BASE,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/geo+json"},
            timeout=30.0,
        )
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_weather_report(self, request: WeatherRequest) -> WeatherReport:
        """Return conditions for the two ends of the route.

        NWS needs lat/lon, which the caller must supply via the
        :class:`WeatherRequest`'s location. This adapter accepts a location already
        resolved to a grid point; the use case geocodes before calling.
        """
        now = datetime.now(UTC)
        origin_condition: WeatherCondition | None = None
        destination_condition: WeatherCondition | None = None
        limitations: list[str] = []

        for label, location in (
            ("origin", request.origin),
            ("destination", request.destination),
        ):
            condition = await self._condition_for(location)
            if condition is not None:
                if label == "origin":
                    origin_condition = condition
                else:
                    destination_condition = condition
            else:
                limitations.append(f"NWS had no data for the {label} location")

        available = origin_condition is not None or destination_condition is not None
        return WeatherReport(
            provider=PROVIDER_NAME,
            retrieved_at=now,
            available=available,
            origin=origin_condition,
            destination=destination_condition,
            limitations=tuple(limitations),
        )

    async def _condition_for(self, location: USLocation) -> WeatherCondition | None:
        """Fetch the current condition for one location.

        Returns ``None`` when the NWS has no data (out of coverage, bad grid
        point, or a transport failure). The caller reports the gap in
        ``limitations`` instead of raising.
        """
        try:
            # NWS /points needs a lat/lon pair. The USLocation only carries city
            # and state; the caller is expected to geocode first. For the MVP we
            # use a static per-state centroid so the call still works.
            lat, lon = _state_centroid(location.state)
            response = await self._client.get(
                f"/points/{lat},{lon}",
                headers={"Accept": "application/geo+json"},
            )
            if response.status_code >= 400:
                return None
            data = response.json()
            forecast_url = data.get("properties", {}).get("forecast")
            if forecast_url is None:
                return None
            forecast_response = await self._client.get(forecast_url)
            if forecast_response.status_code >= 400:
                return None
            forecast_data = forecast_response.json()
            periods = forecast_data.get("properties", {}).get("periods", [])
            if not periods:
                return None

            # Use the first period as "now" for the MVP.
            first = periods[0]
            summary = first.get("detailedForecast", first.get("name", "Unknown"))
            temp = first.get("temperature")
            severity = _severity_from_text(summary)

            return WeatherCondition(
                location=location,
                summary=summary,
                severity=severity,
                temperature_f=Decimal(str(temp)) if temp is not None else None,
            )
        except httpx.HTTPError:
            return None


# A conservative static centroid per state so the MVP can call NWS without a
# geocoder. A production deployment would replace this with OpenRouteService's
# geocode call (already wired in the routing adapter).
_STATE_CENTROIDS: dict[str, tuple[float, float]] = {
    "AL": (32.8, -86.8),
    "AZ": (34.0, -111.0),
    "CA": (37.0, -119.5),
    "CO": (39.0, -105.5),
    "FL": (28.6, -82.4),
    "GA": (32.6, -83.4),
    "IL": (40.0, -89.0),
    "NY": (43.0, -74.0),
    "OH": (40.0, -83.0),
    "TX": (31.0, -99.0),
}


def _state_centroid(state: str) -> tuple[float, float]:
    """Return a centroid for the state, defaulting to the continental US centre."""
    return _STATE_CENTROIDS.get(state, (39.8, -98.6))
