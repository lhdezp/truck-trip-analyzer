"""Common exceptions shared by every layer of the application."""

from __future__ import annotations


class AppError(Exception):
    """Base class for every error raised deliberately by the application.

    Infrastructure and providers must translate their own failures into this
    hierarchy so upper layers never depend on third-party exception types.
    """

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, object] = dict(details) if details else {}

    def __str__(self) -> str:
        return self.message


class ConfigurationError(AppError):
    """Raised when the application cannot be configured safely."""


# Failure categories carried in ``ProviderError.details["kind"]``. They live next to
# the error so every layer can branch on them without importing an adapter.
PROVIDER_KIND_UNAVAILABLE = "unavailable"
PROVIDER_KIND_UNAUTHORIZED = "unauthorized"
PROVIDER_KIND_REJECTED = "rejected"
PROVIDER_KIND_PAYLOAD_TOO_LARGE = "payload_too_large"


class ProviderError(AppError):
    """An external provider failed or returned something unusable.

    Adapters translate SDK, transport and parsing failures into this type so upper
    layers never depend on a vendor exception class.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.provider = provider

    @property
    def kind(self) -> str | None:
        """Stable failure category, when the adapter classified the error.

        Callers branch on this instead of parsing prose: ``unavailable`` means the
        service is down (retry later), ``unauthorized`` means the credentials must be
        fixed, and ``payload_too_large``/``rejected`` mean the request itself must
        change.
        """
        kind = self.details.get("kind")
        return kind if isinstance(kind, str) else None
