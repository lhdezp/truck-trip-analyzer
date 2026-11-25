"""Freight Data Watch market data adapter."""

from app.infrastructure.market.freight_datawatch.provider import (
    PROVIDER_NAME,
    FreightDataWatchClient,
    FreightDataWatchMarketProvider,
)

__all__ = [
    "PROVIDER_NAME",
    "FreightDataWatchClient",
    "FreightDataWatchMarketProvider",
]
