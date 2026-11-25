"""US location value object."""

from __future__ import annotations

import re

from pydantic import Field, field_validator

from app.domain.base import ValueObject

# 50 states plus District of Columbia and Puerto Rico.
_US_STATE_CODES = frozenset(
    {
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "DC",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "PR",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
    }
)

_ZIP_PATTERN = re.compile(r"\d{5}(-\d{4})?")


class USLocation(ValueObject):
    """City and state inside the United States.

    Postal codes are strings because ``00501`` is not the integer 501. Accepts both
    ZIP and ZIP+4; rejects anything else instead of guessing a correction.
    """

    city: str = Field(min_length=1, max_length=80)
    state: str = Field(min_length=2, max_length=2)
    postal_code: str | None = None
    country: str = Field(default="US", frozen=True)

    @field_validator("city")
    @classmethod
    def _normalise_city(cls, value: str) -> str:
        normalised = " ".join(value.split())
        if not normalised:
            raise ValueError("city must not be blank")
        return normalised

    @field_validator("state")
    @classmethod
    def _validate_state(cls, value: str) -> str:
        code = value.strip().upper()
        if code not in _US_STATE_CODES:
            raise ValueError(f"{value!r} is not a valid US state or territory code")
        return code

    @field_validator("postal_code")
    @classmethod
    def _validate_postal_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        postcode = value.strip()
        if _ZIP_PATTERN.fullmatch(postcode) is None:
            raise ValueError(f"{value!r} is not a valid US ZIP code")
        return postcode

    def __str__(self) -> str:
        if self.postal_code:
            return f"{self.city}, {self.state} {self.postal_code}"
        return f"{self.city}, {self.state}"
