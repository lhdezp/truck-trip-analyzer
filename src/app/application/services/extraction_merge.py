"""Consolidation of per-image extractions.

The vision provider reads one screenshot per request. When the user sends several
captures of the same offer, the application service merges them here, in Python, with
rules that can be read and audited:

- values that agree keep one copy, with every supporting reference preserved;
- values that disagree keep the first reading but drop to ``LOW`` confidence and
  produce an explicit :class:`Contradiction`;
- fields seen in only some captures stay ``MEDIUM``: partial agreement is not proof;
- nothing is averaged. Two different weights do not make a third weight.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.application.schemas.extraction import Contradiction, LoadExtraction
from app.domain.entities.load import LoadOffer
from app.domain.exceptions import DomainValidationError
from app.domain.value_objects.provenance import ConfidenceLevel, DataSource, SourcedField

_LOAD_FIELDS: tuple[str, ...] = (
    "broker",
    "reference_number",
    "origin",
    "destination",
    "announced_distance",
    "price_offered",
    "commodity",
    "weight",
    "pieces",
    "dimensions",
    "pickup_window",
    "delivery_window",
    "required_equipment",
    "special_requirements",
    "notes",
)

# When two sources agree, the more direct one represents the merged field.
_SOURCE_PRIORITY: dict[DataSource, int] = {
    DataSource.USER_PROVIDED: 5,
    DataSource.EXTRACTED: 4,
    DataSource.API: 3,
    DataSource.CALCULATED: 2,
    DataSource.ESTIMATED: 1,
}


def _union[T](groups: Sequence[Sequence[T]]) -> list[T]:
    """Concatenate and deduplicate while preserving the first-seen order."""
    return list(dict.fromkeys(item for group in groups for item in group))


def _describe(field: SourcedField[Any]) -> str:
    refs = ", ".join(field.evidence_refs) or "unknown source"
    return f"{field.value} ({refs})"


def _merge_field(
    name: str,
    fields: Sequence[SourcedField[Any] | None],
    *,
    total_sources: int,
) -> tuple[SourcedField[Any] | None, Contradiction | None]:
    present = [field for field in fields if field is not None]
    if not present:
        return None, None

    reference = present[0]
    evidence_parts = [field.evidence for field in present if field.evidence]
    evidence = " | ".join(dict.fromkeys(evidence_parts)) or None
    refs = tuple(_union([field.evidence_refs for field in present]))
    observed = [field.observed_at for field in present if field.observed_at is not None]
    source = max(
        (field.source for field in present),
        key=lambda item: _SOURCE_PRIORITY.get(item, 0),
    )

    if any(field.value != reference.value for field in present[1:]):
        contradiction = Contradiction(
            field=name,
            description=(
                f"{name} disagrees across captures: "
                + "; ".join(_describe(field) for field in present)
            ),
            evidence_refs=refs,
        )
        return (
            SourcedField[Any](
                value=reference.value,
                source=source,
                confidence=ConfidenceLevel.LOW,
                evidence=evidence,
                evidence_refs=refs,
                observed_at=min(observed) if observed else None,
            ),
            contradiction,
        )

    confidence = (
        ConfidenceLevel.HIGH
        if len(present) == total_sources and evidence is not None
        else ConfidenceLevel.MEDIUM
    )
    return (
        SourcedField[Any](
            value=reference.value,
            source=source,
            confidence=confidence,
            evidence=evidence,
            evidence_refs=refs,
            observed_at=min(observed) if observed else None,
        ),
        None,
    )


def _merge_contradictions(items: Sequence[Contradiction]) -> list[Contradiction]:
    merged: dict[tuple[str, str], Contradiction] = {}
    for item in items:
        key = (item.field, item.description)
        existing = merged.get(key)
        if existing is None:
            merged[key] = item
            continue
        merged[key] = Contradiction(
            field=item.field,
            description=item.description,
            evidence_refs=tuple(_union([existing.evidence_refs, item.evidence_refs])),
        )
    return list(merged.values())


def _join_unique(values: Sequence[str | None]) -> str | None:
    unique = _union([[value] for value in values if value])
    return " + ".join(unique) if unique else None


def merge_extractions(extractions: Sequence[LoadExtraction]) -> LoadExtraction:
    """Combine the extractions of every readable capture into one result."""
    if not extractions:
        raise DomainValidationError("at least one extraction is required to merge")
    if len(extractions) == 1:
        return extractions[0]

    total_sources = len(extractions)
    values: dict[str, Any] = {}
    contradictions: list[Contradiction] = []

    for name in _LOAD_FIELDS:
        merged, contradiction = _merge_field(
            name,
            [getattr(extraction.load, name) for extraction in extractions],
            total_sources=total_sources,
        )
        if merged is not None:
            values[name] = merged
        if contradiction is not None:
            contradictions.append(contradiction)

    timestamps: list[datetime] = [extraction.extracted_at for extraction in extractions]

    return LoadExtraction(
        load=LoadOffer.model_validate(values),
        contradictions=_merge_contradictions(
            [*contradictions, *(c for e in extractions for c in e.contradictions)]
        ),
        ambiguous_fields=_union([list(e.ambiguous_fields) for e in extractions]),
        warnings=_union([list(e.warnings) for e in extractions]),
        images_analyzed=sum(e.images_analyzed for e in extractions),
        provider=_join_unique([e.provider for e in extractions]) or "unknown",
        model=_join_unique([e.model for e in extractions]),
        raw_text=None,
        extracted_at=max(timestamps),
    )
