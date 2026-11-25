"""Weather port."""

from __future__ import annotations

from typing import Protocol

from app.application.schemas.weather import WeatherReport, WeatherRequest


class WeatherProvider(Protocol):
    """Returns conditions for the ends of a route.

    An implementation that cannot answer must return ``available=False`` with a
    limitation, not raise into the analysis pipeline.
    """

    async def get_weather_report(self, request: WeatherRequest) -> WeatherReport: ...
