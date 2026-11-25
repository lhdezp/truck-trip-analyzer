"""Wire schemas for Gemini structured output.

These models describe what the model is allowed to *say*, not what the domain
believes. They are deliberately flat and explicit:

- every value is wrapped with its verbatim ``evidence`` so a reader can tell an
  observation from a guess;
- every value is optional, because a screenshot that does not show a field must
  produce ``null`` rather than a plausible default;
- nothing here performs arithmetic, converts units or normalises labels. That is
  the job of :mod:`app.infrastructure.ai.gemini.mapping`, in Python.

``extra="ignore"`` instead of the project-wide ``extra="forbid"`` is intentional: a
wire model is a transport shape, and its JSON schema is sent to Gemini. Forbidding
extra keys emits ``additionalProperties: false`` into the response schema, which the
API does not accept. Strictness belongs to the domain construction that follows.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class WireModel(BaseModel):
    """Base for response-schema models."""

    model_config = ConfigDict(extra="ignore")


class WireText(WireModel):
    """A free-text value copied from the screenshot."""

    value: str | None = None
    evidence: str | None = None


class WireNumber(WireModel):
    """A decimal number copied from the screenshot, in the unit named by its field."""

    value: float | None = None
    evidence: str | None = None


class WireInteger(WireModel):
    """A whole number copied from the screenshot."""

    value: int | None = None
    evidence: str | None = None


class WirePrice(WireModel):
    """The offered amount, exactly as published.

    ``total_usd`` and ``rate_per_mile_usd`` are separate because load boards publish
    either one or both. The model must copy what it sees; converting between them is
    forbidden here and handled deterministically later, if at all.
    """

    total_usd: float | None = None
    rate_per_mile_usd: float | None = None
    evidence: str | None = None


class WireLocation(WireModel):
    """A city/state pair printed on the offer."""

    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    evidence: str | None = None


class WireTimeWindow(WireModel):
    """Pickup or delivery window, as local wall-clock ISO 8601 strings."""

    start: str | None = None
    end: str | None = None
    evidence: str | None = None


class WireDimensions(WireModel):
    """Cargo dimensions in inches. All axes or none: a partial box is not a box."""

    length_in: float | None = None
    width_in: float | None = None
    height_in: float | None = None
    evidence: str | None = None


class WireList(WireModel):
    """A list of short phrases, each copied from the screenshot."""

    values: list[str] = Field(default_factory=list)
    evidence: str | None = None


class WireOffer(WireModel):
    """One load offer as visible in a single screenshot."""

    broker: WireText | None = None
    reference_number: WireText | None = None
    origin: WireLocation | None = None
    destination: WireLocation | None = None
    announced_distance_miles: WireNumber | None = None
    price: WirePrice | None = None
    commodity: WireText | None = None
    weight_pounds: WireNumber | None = None
    pieces: WireInteger | None = None
    dimensions: WireDimensions | None = None
    pickup_window: WireTimeWindow | None = None
    delivery_window: WireTimeWindow | None = None
    required_equipment: WireText | None = None
    special_requirements: WireList | None = None
    notes: WireText | None = None


class WireContradiction(WireModel):
    """A field the screenshot itself states in two incompatible ways."""

    field: str = Field(min_length=1)
    description: str = Field(min_length=1)
    evidence_quotes: list[str] = Field(default_factory=list)


class WireExtraction(WireModel):
    """Everything the model reports for one screenshot."""

    is_load_offer: bool = True
    unreadable: bool = False
    offers: list[WireOffer] = Field(default_factory=list)
    contradictions: list[WireContradiction] = Field(default_factory=list)
    ambiguous_fields: list[str] = Field(default_factory=list)
