"""Load analysis endpoint: multipart image upload to a structured result.

The body accepts one or more image files plus an optional context string. The
response is the stable :class:`LoadAnalysisResult`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.application.schemas.extraction import MAX_IMAGE_BYTES, ImageInput
from app.application.schemas.result import LoadAnalysisResult
from app.application.use_cases.analyze_load import AnalyzeLoadUseCase
from app.config import get_settings
from app.exceptions import AppError
from app.presentation.api.deps import DefaultLoadConfig, build_use_case
from app.presentation.api.routers.auth import AuthedUser

router = APIRouter(prefix="/analyze", tags=["analysis"])

_MEDIA_TYPES = ("image/jpeg", "image/png", "image/webp")


@router.post("")
async def analyze(
    user: AuthedUser,
    use_case: Annotated[AnalyzeLoadUseCase, Depends(_use_case)],
    images: Annotated[list[UploadFile], File(min_length=1)],
    context: str | None = None,
) -> LoadAnalysisResult:
    """Run the full analysis on the uploaded screenshots.

    The endpoint is stateless: each call re-extracts the offer. Persistence of the
    result is a separate concern (V0.9) and does not gate this call.
    """
    inputs: list[ImageInput] = []
    for file in images:
        content = await file.read()
        media_type = file.content_type or "application/octet-stream"
        if media_type not in _MEDIA_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported media type '{media_type}'; "
                f"accepted: {', '.join(_MEDIA_TYPES)}",
            )
        if len(content) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Image exceeds {MAX_IMAGE_BYTES} bytes; got {len(content)}",
            )
        inputs.append(
            ImageInput(
                content=content,
                media_type=media_type,
                reference=file.filename or "image",
            )
        )

    try:
        return await use_case.run(inputs, config=DefaultLoadConfig(), context=context)
    except AppError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


def _use_case() -> AnalyzeLoadUseCase:
    settings = get_settings()
    return build_use_case(settings)
