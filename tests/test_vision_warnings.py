"""The analysis must name the vision gap instead of collapsing every failure.

An outage, an oversized request and an unreadable screenshot lead to different user
actions, so they carry different warning codes.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.application.schemas.extraction import ImageInput
from app.application.use_cases.analyze_load import (
    CODE_VISION_FAILED,
    CODE_VISION_PAYLOAD_TOO_LARGE,
    CODE_VISION_UNAUTHORIZED,
    CODE_VISION_UNAVAILABLE,
    AnalyzeLoadUseCase,
)
from app.domain.rules.recommendation import ProfitThresholds
from app.domain.value_objects.money import Money, RatePerMile
from app.exceptions import (
    PROVIDER_KIND_PAYLOAD_TOO_LARGE,
    PROVIDER_KIND_UNAUTHORIZED,
    PROVIDER_KIND_UNAVAILABLE,
    ProviderError,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


class _Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class _Config:
    thresholds = ProfitThresholds(
        minimum_net_profit=Money(amount=Decimal(0)),
        minimum_net_rpm=RatePerMile(amount=Decimal(0)),
    )
    vehicle = None


class _FailingVision:
    def __init__(self, error: ProviderError) -> None:
        self._error = error

    async def extract_load(
        self, images: Sequence[ImageInput], *, context: str | None = None
    ) -> None:
        raise self._error


def _use_case(error: ProviderError) -> AnalyzeLoadUseCase:
    return AnalyzeLoadUseCase(
        vision=_FailingVision(error),
        market=None,
        routing=None,
        weather=None,
        clock=_Clock(),
    )


@pytest.mark.parametrize(
    ("kind", "expected_code"),
    [
        (PROVIDER_KIND_UNAVAILABLE, CODE_VISION_UNAVAILABLE),
        (PROVIDER_KIND_UNAUTHORIZED, CODE_VISION_UNAUTHORIZED),
        (PROVIDER_KIND_PAYLOAD_TOO_LARGE, CODE_VISION_PAYLOAD_TOO_LARGE),
        ("rejected", CODE_VISION_FAILED),
    ],
)
async def test_vision_failures_are_classified(kind: str, expected_code: str) -> None:
    error = ProviderError("boom", provider="gemini", details={"kind": kind})
    image = ImageInput(content=PNG, media_type="image/png", reference="telegram:x")

    result = await _use_case(error).run([image], config=_Config())

    assert expected_code in {warning.code for warning in result.warnings}
