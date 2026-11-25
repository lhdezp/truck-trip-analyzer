"""Domain exceptions."""

from __future__ import annotations

from app.exceptions import AppError


class DomainError(AppError):
    """Base class for business rule violations."""


class DomainValidationError(DomainError):
    """Raised when a value would violate a domain invariant.

    Pydantic already rejects malformed input at construction time. This error covers
    rules that only make sense in business terms, such as conflicting load data.
    """
