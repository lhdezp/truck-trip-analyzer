"""Retrieve finished analyses from persistence (V0.9)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.schemas.result import LoadAnalysisResult
from app.application.use_cases.analyze_load import AnalyzeLoadUseCase
from app.presentation.api.deps import resolve_use_case
from app.presentation.api.routers.auth import AuthedUser

router = APIRouter(prefix="/load", tags=["history"])


@router.get("/{analysis_id}")
async def get_analysis(
    user: AuthedUser,
    use_case: Annotated[AnalyzeLoadUseCase, Depends(resolve_use_case)],
    analysis_id: str,
) -> LoadAnalysisResult:
    """Return one analysis by id. 404 when it is not in the store."""
    result = await use_case.repository.get(analysis_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No analysis with id '{analysis_id}'",
        )
    return result


@router.get("/history")
async def list_history(
    user: AuthedUser,
    use_case: Annotated[AnalyzeLoadUseCase, Depends(resolve_use_case)],
    limit: int = 20,
) -> list[LoadAnalysisResult]:
    """Return the most recent analyses, newest first."""
    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="limit must be between 1 and 100",
        )
    return await use_case.repository.list_recent(limit=limit)
