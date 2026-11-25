"""Pydantic contracts exchanged by use cases and interfaces."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Schema(BaseModel):
    """Application contract.

    ``extra="forbid"`` is intentional: a provider or client that invents fields gets a
    validation error instead of silently polluting the result.
    """

    model_config = ConfigDict(extra="forbid")
