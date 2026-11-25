"""Health check: liveness without touching any provider."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Return 200 when the process is up. No provider calls: a dead key must not
    fail the health probe, or the API would report itself down whenever a
    credential rotates."""
    return {"status": "ok"}
