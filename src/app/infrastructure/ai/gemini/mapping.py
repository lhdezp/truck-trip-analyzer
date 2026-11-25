"""Translate Gemini wire output into domain values.

This module is the only place where provider text becomes an application object, and
it is deliberately suspicious:

- every value is revalidated by the domain value object that owns the rule;
- a value that fails validation is *dropped and flagged*, never repaired;
- unit conversion and arithmetic are explicit and reported through
  :class:`~app.domain.value_objects.provenance.DataSource`.

A field the model omitted stays omitted. Nothing is defaulted.
"""

from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import ValidationError

from app.application.schemas.extraction import Contradiction, LoadExtraction
from app.domain.entities.load import LoadOffer
from app.domain.value_objects.dimensions import Dimensions
from app.domain.value_objects.distance import Distance
from app.domain.value_objects.equipment import EquipmentType
from app.domain.value_objects.location import USLocation
from app.domain.value_objects.money import Money
from app.domain.value_objects.provenance import ConfidenceLevel, DataSource, SourcedField
from app.domain.value_objects.time_window import TimeWindow
from app.domain.value_objects.weight import Weight
from app.infrastructure.ai.gemini.wire import (
    WireDimensions,
    WireExtraction,
    WireInteger,
    WireList,
    WireLocation,
    WireNumber,
    WireOffer,
    WirePrice,
    WireText,
    WireTimeWindow,
)

LocationField = Literal["origin", "destination"]

# Labels seen on US load boards. Only unambiguous synonyms are listed: a "step deck"
# is not a flatbed and an unknown trailer type must stay unknown instead of being
# collapsed into the wrong category.
_EQUIPMENT_ALIASES: dict[str, EquipmentType] = {
    "box truck": EquipmentType.BOX_TRUCK,
    "box trucks": EquipmentType.BOX_TRUCK,
    "boxtruck": EquipmentType.BOX_TRUCK,
    "cube truck": EquipmentType.BOX_TRUCK,
    "cube van": EquipmentType.BOX_TRUCK,
    "straight truck": EquipmentType.STRAIGHT_TRUCK,
    "straight": EquipmentType.STRAIGHT_TRUCK,
    "cargo van": EquipmentType.CARGO_VAN,
    "cargo": EquipmentType.CARGO_VAN,
    "sprinter": EquipmentType.CARGO_VAN,
    "sprinter van": EquipmentType.CARGO_VAN,
    "transit van": EquipmentType.CARGO_VAN,
    "dry van": EquipmentType.DRY_VAN,
    "dryvan": EquipmentType.DRY_VAN,
    "van trailer": EquipmentType.DRY_VAN,
    "reefer": EquipmentType.REEFER,
    "reefer trailer": EquipmentType.REEFER,
    "refrigerated": EquipmentType.REEFER,
    "refrigerated van": EquipmentType.REEFER,
    "refrigerated trailer": EquipmentType.REEFER,
    "flatbed": EquipmentType.FLATBED,
    "flat bed": EquipmentType.FLATBED,
    "flatbed trailer": EquipmentType.FLATBED,
    "other": EquipmentType.OTHER,
}


def _to_decimal(value: float | None) -> Decimal | None:
    """Convert a JSON number without inventing precision.

    ``Decimal(str(1250.0))`` yields ``1250.0``; ``Decimal(1250.0)`` would drag in the
    binary representation. Non-finite numbers are rejected instead of poisoning the
    financial path.
    """
    if value is None or not math.isfinite(value):
        return None
    return Decimal(str(value))


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    normalised = " ".join(value.split())
    return normalised or None


def _confidence(evidence: str | None) -> ConfidenceLevel:
    """Evidence raises confidence; its absence lowers it but never to zero."""
    return ConfidenceLevel.HIGH if _clean(evidence) else ConfidenceLevel.MEDIUM


def _sourced[T](
    value: T,
    *,
    evidence: str | None,
    image_ref: str,
    observed_at: datetime,
    source: DataSource = DataSource.EXTRACTED,
    confidence: ConfidenceLevel | None = None,
) -> SourcedField[T]:
    return SourcedField[T](
        value=value,
        source=source,
        confidence=confidence if confidence is not None else _confidence(evidence),
        evidence=_clean(evidence),
        evidence_refs=(image_ref,),
        observed_at=observed_at,
    )


def _is_date_only(raw: str) -> bool:
    """True for ``YYYY-MM-DD``: a day was printed, an hour was not."""
    return "T" not in raw and " " not in raw


def _normalise_equipment(raw: str) -> EquipmentType | None:
    key = " ".join(raw.lower().replace("_", " ").replace("-", " ").split())
    return _EQUIPMENT_ALIASES.get(key)


class _OfferMapper:
    """Builds one :class:`LoadOffer` from a wire offer, collecting defects."""

    def __init__(self, *, image_ref: str, observed_at: datetime) -> None:
        self.image_ref = image_ref
        self.observed_at = observed_at
        self.ambiguous: list[str] = []
        self.contradictions: list[Contradiction] = []

    def flag(self, field: str) -> None:
        if field not in self.ambiguous:
            self.ambiguous.append(field)

    def _field[T](self, value: T, evidence: str | None) -> SourcedField[T]:
        return _sourced(
            value,
            evidence=evidence,
            image_ref=self.image_ref,
            observed_at=self.observed_at,
        )

    def text(self, field: str, wire: WireText | None) -> SourcedField[str] | None:
        if wire is None:
            return None
        value = _clean(wire.value)
        if value is None:
            if wire.value is not None:
                self.flag(field)
            return None
        return self._field(value, wire.evidence)

    def distance(self, wire: WireNumber | None) -> SourcedField[Distance] | None:
        if wire is None or wire.value is None:
            return None
        miles = _to_decimal(wire.value)
        if miles is None or miles < 0:
            self.flag("announced_distance")
            return None
        return self._field(Distance(miles=miles), wire.evidence)

    def weight(self, wire: WireNumber | None) -> SourcedField[Weight] | None:
        if wire is None or wire.value is None:
            return None
        pounds = _to_decimal(wire.value)
        if pounds is None or pounds <= 0:
            self.flag("weight")
            return None
        return self._field(Weight(pounds=pounds), wire.evidence)

    def pieces(self, wire: WireInteger | None) -> SourcedField[int] | None:
        if wire is None or wire.value is None:
            return None
        if wire.value < 1:
            self.flag("pieces")
            return None
        return self._field(wire.value, wire.evidence)

    def price(
        self,
        wire: WirePrice | None,
        *,
        announced_distance: SourcedField[Distance] | None,
    ) -> SourcedField[Money] | None:
        """Read the offered amount.

        A total is copied as-is. A per-mile rate is only turned into a total when the
        offer also publishes its distance, and the result is marked ``CALCULATED``
        because it is the product of two visible numbers rather than a printed figure.
        """
        if wire is None:
            return None

        total = _to_decimal(wire.total_usd)
        if total is not None:
            if total < 0:
                self.flag("price_offered")
                return None
            return self._field(Money(amount=total), wire.evidence)

        rate = _to_decimal(wire.rate_per_mile_usd)
        if rate is None:
            self.flag("price_offered")
            return None
        if rate < 0 or announced_distance is None:
            self.flag("price_offered")
            return None

        miles = announced_distance.value
        derived = f"{rate} USD/mi x {miles} mi"
        evidence = " | ".join(
            part for part in (_clean(wire.evidence), f"derived: {derived}") if part
        )
        return _sourced(
            Money(amount=rate * miles.miles),
            evidence=evidence,
            image_ref=self.image_ref,
            observed_at=self.observed_at,
            source=DataSource.CALCULATED,
            confidence=ConfidenceLevel.MEDIUM,
        )

    def location(
        self,
        field: LocationField,
        wire: WireLocation | None,
    ) -> SourcedField[USLocation] | None:
        if wire is None:
            return None
        city = _clean(wire.city)
        state = _clean(wire.state)
        if city is None or state is None:
            self.flag(field)
            return None
        try:
            location = USLocation(
                city=city,
                state=state,
                postal_code=_clean(wire.postal_code),
            )
        except ValidationError:
            self.flag(field)
            return None
        return self._field(location, wire.evidence)

    def window(
        self,
        field: str,
        wire: WireTimeWindow | None,
    ) -> SourcedField[TimeWindow] | None:
        if wire is None:
            return None
        raw_start = _clean(wire.start)
        if raw_start is None:
            return None
        raw_end = _clean(wire.end)
        try:
            window = TimeWindow(
                start=datetime.fromisoformat(raw_start),
                end=datetime.fromisoformat(raw_end) if raw_end else None,
            )
        except (ValueError, TypeError):
            # ``TypeError`` covers mixing an aware and a naive boundary; neither is
            # repaired, because assuming a timezone would falsify the offer.
            self.flag(field)
            return None
        if _is_date_only(raw_start) or (raw_end is not None and _is_date_only(raw_end)):
            # A date without an hour is stored at midnight so the day is preserved,
            # but it is flagged: the hour is unknown, not 00:00.
            self.flag(field)
        return self._field(window, wire.evidence)

    def dimensions(self, wire: WireDimensions | None) -> SourcedField[Dimensions] | None:
        if wire is None:
            return None
        length = _to_decimal(wire.length_in)
        width = _to_decimal(wire.width_in)
        height = _to_decimal(wire.height_in)
        if length is None and width is None and height is None:
            return None
        if length is None or width is None or height is None:
            self.flag("dimensions")
            return None
        if length <= 0 or width <= 0 or height <= 0:
            self.flag("dimensions")
            return None
        return self._field(
            Dimensions(length_in=length, width_in=width, height_in=height),
            wire.evidence,
        )

    def equipment(self, wire: WireText | None) -> SourcedField[EquipmentType] | None:
        if wire is None:
            return None
        label = _clean(wire.value)
        if label is None:
            return None
        equipment = _normalise_equipment(label)
        if equipment is None:
            self.flag("required_equipment")
            return None
        return self._field(equipment, wire.evidence)

    def requirements(self, wire: WireList | None) -> SourcedField[tuple[str, ...]] | None:
        if wire is None:
            return None
        items = tuple(dict.fromkeys(cleaned for item in wire.values if (cleaned := _clean(item))))
        if not items:
            return None
        return self._field(items, wire.evidence)


def _map_contradictions(wire: WireExtraction, image_ref: str) -> list[Contradiction]:
    contradictions: dict[tuple[str, str], Contradiction] = {}
    for item in wire.contradictions:
        field = _clean(item.field)
        description = _clean(item.description)
        if field is None or description is None:
            continue
        key = (field, description)
        contradictions.setdefault(
            key,
            Contradiction(field=field, description=description, evidence_refs=(image_ref,)),
        )
    return list(contradictions.values())


def _normalise_field_name(raw: str) -> str | None:
    name = "_".join(raw.strip().lower().split())
    return name or None


def map_extraction(
    wire: WireExtraction,
    *,
    image_ref: str,
    observed_at: datetime,
    provider: str,
    model: str | None = None,
    raw_text: str | None = None,
) -> LoadExtraction:
    """Turn one screenshot's wire payload into a :class:`LoadExtraction`.

    A screenshot with several offers yields the first one plus an explicit
    ``multiple_offers_detected`` flag: silently picking one would hide that the user
    has more offers to analyse.
    """
    mapper = _OfferMapper(image_ref=image_ref, observed_at=observed_at)
    warnings: list[str] = []

    if wire.unreadable:
        warnings.append(f"image_unreadable:{image_ref}")
    if not wire.is_load_offer:
        warnings.append(f"not_a_load_offer:{image_ref}")

    offer = wire.offers[0] if wire.offers else WireOffer()
    if len(wire.offers) > 1:
        mapper.flag("multiple_offers_detected")
        warnings.append(f"multiple_offers_detected:{image_ref}")
    elif not wire.offers and wire.is_load_offer and not wire.unreadable:
        warnings.append(f"no_offer_visible:{image_ref}")

    announced_distance = mapper.distance(offer.announced_distance_miles)
    load = LoadOffer(
        broker=mapper.text("broker", offer.broker),
        reference_number=mapper.text("reference_number", offer.reference_number),
        origin=mapper.location("origin", offer.origin),
        destination=mapper.location("destination", offer.destination),
        announced_distance=announced_distance,
        price_offered=mapper.price(offer.price, announced_distance=announced_distance),
        commodity=mapper.text("commodity", offer.commodity),
        weight=mapper.weight(offer.weight_pounds),
        pieces=mapper.pieces(offer.pieces),
        dimensions=mapper.dimensions(offer.dimensions),
        pickup_window=mapper.window("pickup_window", offer.pickup_window),
        delivery_window=mapper.window("delivery_window", offer.delivery_window),
        required_equipment=mapper.equipment(offer.required_equipment),
        special_requirements=mapper.requirements(offer.special_requirements),
        notes=mapper.text("notes", offer.notes),
    )

    ambiguous = list(mapper.ambiguous)
    for raw in wire.ambiguous_fields:
        name = _normalise_field_name(raw)
        if name is not None and name not in ambiguous:
            ambiguous.append(name)

    return LoadExtraction(
        load=load,
        contradictions=[
            *mapper.contradictions,
            *_map_contradictions(wire, image_ref),
        ],
        ambiguous_fields=ambiguous,
        warnings=warnings,
        images_analyzed=1,
        provider=provider,
        model=model,
        raw_text=raw_text,
        extracted_at=observed_at,
    )
