"""Freight Data Watch market data adapter.

Reads national modeled equipment rates and returns them as
:class:`~app.application.schemas.analysis.MarketReference`. The provider only
publishes estimates for three equipment categories, so the adapter maps those and
returns an empty list for everything else: returning a trailer rate for a box truck
query would be a category error the analysis would misread as a comparable benchmark.

The adapter sends the explicit ``User-Agent`` the portal requires, translates vendor
failures to :class:`~app.exceptions.ProviderError`, and stamps every reference with
its retrieval time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
from pydantic import ValidationError

from app.application.schemas.analysis import MarketReference, MarketScope
from app.config import Settings
from app.domain.value_objects.equipment import EquipmentType
from app.domain.value_objects.location import USLocation
from app.domain.value_objects.money import RatePerMile
from app.domain.value_objects.provenance import DataSource
from app.exceptions import ConfigurationError, ProviderError
from app.infrastructure.market.freight_datawatch.wire import WireSpecialized

PROVIDER_NAME = "freight_datawatch"
_USER_AGENT = "truck-load-analyzer/0.1 (+https://github.com/truck-load-analyzer)"

# The provider's keys for specialized equipment, mapped to the domain categories the
# analysis recognises. Categories with no provider coverage are deliberately absent:
# an empty reference list is the honest answer, not a substitute number.
_SPECIALIZED_KEY: dict[str, EquipmentType] = {
    "boxTruck": EquipmentType.BOX_TRUCK,
    "hotShot": EquipmentType.STRAIGHT_TRUCK,
    "sprinterVan": EquipmentType.CARGO_VAN,
}


class FreightDataWatchClient:
    """HTTP client for the Freight Data Watch API."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        key = (
            settings.FREIGHT_DATAWATCH_API_KEY.get_secret_value().strip()
            if settings.FREIGHT_DATAWATCH_API_KEY is not None
            else ""
        )
        if not key:
            raise ConfigurationError(
                "FREIGHT_DATAWATCH_API_KEY is required to start the market adapter"
            )

        base_url = settings.FREIGHT_DATAWATCH_BASE_URL.rstrip("/")
        headers = {
            "Authorization": f"Bearer {key}",
            "X-API-Key": key,
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        }

        self._client = client or httpx.AsyncClient(base_url=base_url, headers=headers, timeout=30.0)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get_specialized(self) -> WireSpecialized:
        try:
            response = await self._client.get("/market/specialized")
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Freight Data Watch request failed: {exc}",
                provider=PROVIDER_NAME,
            ) from exc
        if response.status_code >= 400:
            raise ProviderError(
                f"Freight Data Watch returned {response.status_code} "
                f"for /market/specialized: {response.text[:200]}",
                provider=PROVIDER_NAME,
            )
        try:
            return WireSpecialized.model_validate(response.json())
        except ValidationError as exc:
            raise ProviderError(
                "Freight Data Watch returned a payload that does not match the specialized schema",
                provider=PROVIDER_NAME,
                details={"errors": exc.error_count()},
            ) from exc


class FreightDataWatchMarketProvider:
    """Answers the :class:`MarketDataProvider` port using Freight Data Watch."""

    name: str = PROVIDER_NAME

    def __init__(self, client: FreightDataWatchClient) -> None:
        self._client = client

    async def fetch_market_references(
        self,
        *,
        equipment: EquipmentType,
        origin: USLocation,
        destination: USLocation,
    ) -> list[MarketReference]:
        """Return the provider's rate for ``equipment`` when it publishes one.

        The provider's specialized endpoint is national and equipment-scoped only: it
        does not vary by lane, so ``origin`` and ``destination`` are accepted to
        satisfy the port contract but do not change the reference. That is documented,
        not a silent fallback.
        """
        wire = await self._client._get_specialized()
        references: list[MarketReference] = []
        for key, category in _SPECIALIZED_KEY.items():
            if category is not equipment:
                continue
            block = wire.equipment.get(key)
            if block is None or block.avg_rate is None:
                continue
            references.append(
                MarketReference(
                    rate_per_mile=RatePerMile(amount=Decimal(str(block.avg_rate))),
                    equipment=category,
                    scope=MarketScope.NATIONAL,
                    basis=DataSource.ESTIMATED,
                    provider=PROVIDER_NAME,
                    retrieved_at=(
                        _parse_utc(wire.last_updated) if wire.last_updated else datetime.now(UTC)
                    ),
                    sample_notes=wire.methodology,
                )
            )
        return references


def _parse_utc(value: str) -> datetime:
    """Parse the provider's ISO-8601 timestamp as UTC."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
