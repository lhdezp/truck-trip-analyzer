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
  and never a google-genai or httpx exception class.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from google import genai
from google.genai import types
from pydantic import ValidationError

from app.application.schemas.extraction import ImageInput, LoadExtraction
from app.application.services.extraction_merge import merge_extractions
from app.config import Settings
from app.domain.exceptions import DomainValidationError
from app.exceptions import ConfigurationError, ProviderError
from app.infrastructure.ai.gemini.mapping import map_extraction
from app.infrastructure.ai.gemini.prompt import EXTRACTION_INSTRUCTION, build_extraction_prompt
from app.infrastructure.ai.gemini.wire import WireExtraction

logger = logging.getLogger(__name__)

PROVIDER_NAME = "gemini"
_RETRY_ATTEMPTS = 3


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
            logger.warning("Gemini could not read %s: %s", image.reference, result)

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
                details={"failed_images": failures},
            ) from first_error

        merged = merge_extractions(extractions)
        merged.warnings.extend(f"image_failed:{reference}" for reference in failures)
        return merged

    async def _extract_one(
        self,
        image: ImageInput,
        *,
        context: str | None,
    ) -> LoadExtraction:
        try:
            response = await self._generate(
                model=self._model,
                contents=[
                    build_extraction_prompt(image_reference=image.reference, context=context),
                    types.Part.from_bytes(data=image.content, mime_type=image.media_type),
                ],
                config=self._config,
            )
        except ProviderError:
            raise
        except Exception as exc:
            # Vendor exception classes differ across SDK versions and are not part of
            # this project's contract. Translating broadly keeps the boundary honest.
            raise ProviderError(
                f"Gemini request failed for '{image.reference}'",
                provider=PROVIDER_NAME,
                details={"image": image.reference, "error": type(exc).__name__},
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
