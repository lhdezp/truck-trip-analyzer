"""Base classes for the domain model.

The domain depends on the standard library and Pydantic only. Pydantic is a pure
validation library with no I/O, so it does not violate the dependency rule; see
decision D9 in ``docs/architecture.md``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ValueObject(BaseModel):
    """Immutable, self-validating value.

    Frozen on purpose: money, distances and locations are replaced, never mutated,
    which keeps financial calculations free of accidental aliasing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class Entity(BaseModel):
    """Object with identity whose attributes may evolve over time."""

    model_config = ConfigDict(extra="forbid")
