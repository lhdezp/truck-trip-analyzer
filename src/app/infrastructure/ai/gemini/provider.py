"""Gemini vision adapter.

Design choices worth knowing:

- **One request per image.** Cross-image consolidation happens in
  :func:`app.application.services.extraction_merge.merge_extractions`, where the rules
  are deterministic and auditable. A provider that merges internally would hide its
  conflicts behind a single answer.
- **Structured output, not prose.** The response schema is generated from
  :mod:`wire` models and validated by Pydantic, so a malformed answer fails loudly
  instead of being parsed with string surgery.
- **Vendor errors stop here.** Callers see :class:`~app.exceptions.ProviderError`
  and never a google-genai or httpx exception class. Every failure carries a
  ``kind`` (``unauthorized``, ``unavailable``, ``rejected``, ``payload_too_large``)
  so an outage is never mistaken for an unreadable screenshot.
- **Inline budget.** The screenshot travels as ``inline_data`` (bytes + media type),
  which the API base64-encodes. The total is checked *before* the call: a request
  that cannot fit is rejected with a clear message instead of a vendor 400.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from google import genai
from google.genai import types
from pydantic import ValidationError

from app.application.schemas.extraction import ImageInput, LoadExtraction
from app.application.services.extraction_merge import merge_extractions
from app.config import Settings
from app.domain.exceptions import DomainValidationError
from app.exceptions import (
    PROVIDER_KIND_PAYLOAD_TOO_LARGE,
    PROVIDER_KIND_REJECTED,
    PROVIDER_KIND_UNAUTHORIZED,
    PROVIDER_KIND_UNAVAILABLE,
    ConfigurationError,
    ProviderError,
)
from app.infrastructure.ai.gemini.mapping import map_extraction
from app.infrastructure.ai.gemini.prompt import EXTRACTION_INSTRUCTION, build_extraction_prompt
from app.infrastructure.ai.gemini.wire import WireExtraction

logger = logging.getLogger(__name__)

PROVIDER_NAME = "gemini"
_RETRY_ATTEMPTS = 3

# Failure kinds travel in ``ProviderError.details["kind"]`` so callers can tell an
# outage ("retry later") from a request the API refused ("fix the input"). The
# constants are defined next to the error so no layer imports this adapter for them.
_UNAUTHORIZED_STATUS = frozenset({401})
_UNAVAILABLE_STATUS = frozenset({403, 408, 409, 429})


def _encoded_size(image: ImageInput) -> int:
    """Size of the image once base64-encoded, which is how it travels in the request."""
    return 4 * ((len(image.content) + 2) // 3)


def _status_code(exc: BaseException) -> int | None:
    """Best-effort HTTP status from a vendor exception, without importing its class."""
    for attribute in ("status_code", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
    return None


def _short_reason(exc: BaseException, *, limit: int = 300) -> str:
    """One-line rendering of a vendor error: enough to diagnose, small enough to log.

    Google returns an HTML page for some edge failures; collapsing whitespace keeps
    that from flooding the log while preserving the status and the first sentence.
    """
    text = " ".join(str(exc).split())
    if not text:
        return type(exc).__name__
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _classify_failure(exc: BaseException) -> str:
    """Decide whether the failure is the service's (outage) or the request's.

    ``401`` is called out on its own: a rejected key is a configuration problem, not
    an outage, and the operator has to fix it. ``403`` stays ``unavailable`` because
    Google also answers a blocked network or a region restriction with that status.
    """
    if isinstance(exc, TimeoutError | httpx.TransportError):
        return PROVIDER_KIND_UNAVAILABLE
    status = _status_code(exc)
    if status in _UNAUTHORIZED_STATUS:
        return PROVIDER_KIND_UNAUTHORIZED
    if status is not None and (status in _UNAVAILABLE_STATUS or status >= 500):
        return PROVIDER_KIND_UNAVAILABLE
    return PROVIDER_KIND_REJECTED


def _failure_kind(exc: BaseException) -> str:
    """Kind of an already-translated error, or a classification of a raw one."""
    if isinstance(exc, ProviderError):
        kind = exc.details.get("kind")
        if isinstance(kind, str):
            return kind
    return _classify_failure(exc)


def _describe_failure(exc: BaseException) -> str:
    """Cause for the log, preferring the translated details over the wrapper message."""
    if isinstance(exc, ProviderError):
        status = exc.details.get("status_code")
        reason = exc.details.get("reason")
        if isinstance(reason, str):
            return f"HTTP {status}: {reason}" if status is not None else reason
        error = exc.details.get("error")
        if isinstance(error, str):
            return error
    return _short_reason(exc)


class GenerateContentFn(Protocol):
    """The single SDK call this adapter needs, so it can be replaced in tests."""

    def __call__(
        self,
        *,
        model: str,
        contents: Any,
        config: types.GenerateContentConfig,
    ) -> Awaitable[types.GenerateContentResponse]: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _response_text(response: types.GenerateContentResponse) -> str | None:
    """Return the textual answer, tolerating a response with no text part."""
    try:
        text = response.text
    except (ValueError, AttributeError):
        return None
    return text.strip() if text else None


def _parse_wire(response: types.GenerateContentResponse) -> WireExtraction:
    """Prefer the SDK-parsed object; fall back to parsing the raw JSON text."""
    parsed = response.parsed
    if isinstance(parsed, WireExtraction):
        return parsed
    if isinstance(parsed, dict):
        try:
            return WireExtraction.model_validate(parsed)
        except ValidationError as exc:
            raise ProviderError(
                "Gemini returned a payload that does not match the extraction schema",
                provider=PROVIDER_NAME,
                details={"errors": exc.error_count()},
            ) from exc

    text = _response_text(response)
    if text is None:
        raise ProviderError(
            "Gemini returned an empty response",
            provider=PROVIDER_NAME,
        )
    try:
        return WireExtraction.model_validate_json(text)
    except ValidationError as exc:
        raise ProviderError(
            "Gemini returned JSON that does not match the extraction schema",
            provider=PROVIDER_NAME,
            details={"errors": exc.error_count()},
        ) from exc


def _default_generate(client: genai.Client) -> GenerateContentFn:
    async def generate(
        *,
        model: str,
        contents: Any,
        config: types.GenerateContentConfig,
    ) -> types.GenerateContentResponse:
        return await client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

    return generate


def _build_contents(image: ImageInput, *, context: str | None) -> list[str | types.Part]:
    """The user turn: the instructions as text plus the screenshot as an image part.

    The screenshot travels as ``inline_data`` (raw bytes + media type), never as a
    path or a base64 string inside the prompt: the model must receive an image, not
    a blob of text it has to decode. The instructions stay in the same turn so the
    transcription contract applies to this image and no other.
    """
    return [
        build_extraction_prompt(image_reference=image.reference, context=context),
        types.Part.from_bytes(data=image.content, mime_type=image.media_type),
    ]


class GeminiVisionProvider:
    """Reads load offers from screenshots with Gemini."""

    name: str = PROVIDER_NAME

    def __init__(
        self,
        settings: Settings,
        *,
        client: genai.Client | None = None,
        generate: GenerateContentFn | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        model = settings.GEMINI_MODEL.strip()
        if not model:
            raise ConfigurationError("GEMINI_MODEL is required to start the Gemini vision provider")

        self._model = model
        self._max_images = settings.MAX_IMAGES_PER_ANALYSIS
        self._max_request_bytes = settings.GEMINI_MAX_REQUEST_BYTES
        self._now = now or _utc_now
        self._config = types.GenerateContentConfig(
            system_instruction=EXTRACTION_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=WireExtraction,
            temperature=0,
        )

        if generate is not None:
            self._generate = generate
            return

        api_key = (
            settings.GEMINI_API_KEY.get_secret_value().strip()
            if settings.GEMINI_API_KEY is not None
            else ""
        )
        if not api_key:
            raise ConfigurationError(
                "GEMINI_API_KEY is required to start the Gemini vision provider"
            )

        resolved_client = client or genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=int(settings.GEMINI_TIMEOUT_SECONDS * 1000),
                retry_options=types.HttpRetryOptions(
                    attempts=_RETRY_ATTEMPTS,
                    initial_delay=1.0,
                    max_delay=8.0,
                ),
            ),
        )
        self._generate = _default_generate(resolved_client)

    async def extract_load(
        self,
        images: Sequence[ImageInput],
        *,
        context: str | None = None,
    ) -> LoadExtraction:
        """Extract one offer from each screenshot and merge the readable ones.

        A screenshot that fails is reported as ``image_failed:<reference>`` and the
        analysis continues with the rest. Only when every image fails does the call
        raise: returning an empty extraction would look like "the offer had no data".
        """
        if not images:
            raise DomainValidationError("at least one image is required")
        if len(images) > self._max_images:
            raise DomainValidationError(
                f"at most {self._max_images} images can be analyzed at once, got {len(images)}"
            )
        self._check_request_budget(images)

        results = await asyncio.gather(
            *(self._extract_one(image, context=context) for image in images),
            return_exceptions=True,
        )

        extractions: list[LoadExtraction] = []
        failures: list[str] = []
        for image, result in zip(images, results, strict=True):
            if isinstance(result, LoadExtraction):
                extractions.append(result)
                continue
            failures.append(image.reference)
            logger.warning(
                "Gemini could not read %s (%s, %s, %s bytes): %s",
                image.reference,
                _failure_kind(result),
                image.media_type,
                image.size_bytes,
                _describe_failure(result),
            )

        if not extractions:
            first_error = next(
                (result for result in results if isinstance(result, BaseException)),
                None,
            )
            if len(results) == 1 and isinstance(first_error, ProviderError):
                # A single failure is the caller's answer: keep the original cause so
                # the real reason (bad key, blocked request, timeout) is not erased.
                raise first_error
            raise ProviderError(
                f"Gemini could not read any of the {len(images)} image(s): "
                f"{type(first_error).__name__}",
                provider=PROVIDER_NAME,
                details={
                    "kind": _failure_kind(first_error) if first_error else PROVIDER_KIND_REJECTED,
                    "failed_images": failures,
                },
            ) from first_error

        merged = merge_extractions(extractions)
        merged.warnings.extend(f"image_failed:{reference}" for reference in failures)
        return merged

    def _check_request_budget(self, images: Sequence[ImageInput]) -> None:
        """Refuse the request before the call when the encoded images cannot fit.

        The API receives inline base64 data, so the ceiling applies to the encoded
        total, not to the sum of the raw files. Catching it here turns an opaque
        vendor 400 into a message that names the offending screenshot.
        """
        total = sum(_encoded_size(image) for image in images)
        if total <= self._max_request_bytes:
            return
        largest = max(images, key=_encoded_size)
        raise ProviderError(
            f"The screenshots total {total} bytes once encoded, over the "
            f"{self._max_request_bytes} byte limit for one Gemini request",
            provider=PROVIDER_NAME,
            details={
                "kind": PROVIDER_KIND_PAYLOAD_TOO_LARGE,
                "encoded_bytes": total,
                "max_request_bytes": self._max_request_bytes,
                "largest_image": largest.reference,
                "largest_image_bytes": largest.size_bytes,
            },
        )

    async def _extract_one(
        self,
        image: ImageInput,
        *,
        context: str | None,
    ) -> LoadExtraction:
        try:
            response = await self._generate(
                model=self._model,
                contents=_build_contents(image, context=context),
                config=self._config,
            )
        except ProviderError:
            raise
        except Exception as exc:
            # Vendor exception classes differ across SDK versions and are not part of
            # this project's contract. Translating broadly keeps the boundary honest.
            logger.debug("Gemini transport failure for %s", image.reference, exc_info=True)
            raise ProviderError(
                f"Gemini request failed for '{image.reference}'",
                provider=PROVIDER_NAME,
                details={
                    "kind": _classify_failure(exc),
                    "image": image.reference,
                    "media_type": image.media_type,
                    "size_bytes": image.size_bytes,
                    "status_code": _status_code(exc),
                    "error": type(exc).__name__,
                    "reason": _short_reason(exc),
                },
            ) from exc

        wire = _parse_wire(response)
        return map_extraction(
            wire,
            image_ref=image.reference,
            observed_at=self._now(),
            provider=PROVIDER_NAME,
            model=self._model,
            raw_text=_response_text(response),
        )
