"""Pickup and delivery time windows."""

from __future__ import annotations

from datetime import datetime

from pydantic import model_validator

from app.domain.base import ValueObject


class TimeWindow(ValueObject):
    """A start time with an optional end.

    Times are interpreted in the local time of the associated location. Naive
    datetimes are accepted because a load offer states local wall-clock times and the
    time zone is not always published; they must never be treated as UTC.
    """

    start: datetime
    end: datetime | None = None

    @model_validator(mode="after")
    def _end_must_not_precede_start(self) -> TimeWindow:
        if self.end is not None and self.end < self.start:
            raise ValueError("time window end must not be earlier than its start")
        return self
