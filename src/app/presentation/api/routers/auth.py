"""Authentication: Bearer token check against the configured ``API_SECRET``.

The token is compared in constant time so a timing oracle does not reveal how many
leading characters match.
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings

_bearer_scheme = HTTPBearer(auto_error=False)


def _token_matches(credential: str, secret: str) -> bool:
    """Constant-time comparison to avoid leaking prefix length on a miss."""
    return hmac.compare_digest(credential.encode("utf-8"), secret.encode("utf-8"))


async def require_auth(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer_scheme),
    ],
) -> str:
    """Reject requests without a valid Bearer token.

    In development the ``API_SECRET`` may be empty; the endpoint then accepts any
    non-empty bearer. In production the secret is mandatory (see ``ConfigurationError``
    on boot).
    """
    settings = get_settings()
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    configured = (settings.API_SECRET.get_secret_value() if settings.API_SECRET else "").strip()
    if not configured:
        # Development: no secret configured, so any non-empty token is accepted.
        return credentials.credentials
    if not _token_matches(credentials.credentials, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


AuthedUser = Annotated[str, Depends(require_auth)]
