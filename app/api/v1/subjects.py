"""과목 카탈로그 검색. 온보딩(상담 전)에서도 써야 하므로 진단+상담 관문을 걸지 않는다."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_active_verified_user, get_current_user
from app.models.user import User
from app.schemas.subject import SubjectListResponse, SubjectRead
from app.services import subject_catalog

router = APIRouter(
    prefix="/subjects", tags=["subjects"], dependencies=[Depends(get_active_verified_user)]
)

_CURRICULA = {subject_catalog.CURRICULUM_2015, subject_catalog.CURRICULUM_2022}


def _curriculum(user: User, requested: str | None) -> str:
    if requested in _CURRICULA:
        return requested  # type: ignore[return-value]
    return subject_catalog.curriculum_for_student(
        user.freshman_academic_year, user.current_grade
    )


@router.get("", response_model=SubjectListResponse)
async def list_subjects(
    user: Annotated[User, Depends(get_current_user)],
    curriculum: Annotated[str | None, Query()] = None,
) -> SubjectListResponse:
    """이 학생 교육과정의 과목 전체(수백 개). 시간표의 과목 둘러보기처럼 교과군별로
    훑어볼 때 쓴다 — 검색은 /subjects/search가 더 빠르다."""
    chosen = _curriculum(user, curriculum)
    items = [s for s in subject_catalog.SUBJECTS if s.curriculum == chosen]
    return SubjectListResponse(
        curriculum=chosen, items=[SubjectRead.model_validate(s) for s in items]
    )


@router.get("/search", response_model=SubjectListResponse)
async def search_subjects(
    user: Annotated[User, Depends(get_current_user)],
    q: Annotated[str, Query(max_length=40)] = "",
    curriculum: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SubjectListResponse:
    """"수"를 치면 공통수학1, 수학Ⅰ… 이 학생의 교육과정 과목만 돌려준다."""
    chosen = _curriculum(user, curriculum)
    items = subject_catalog.search(q, chosen, limit)
    return SubjectListResponse(
        curriculum=chosen, items=[SubjectRead.model_validate(s) for s in items]
    )


@router.get("/common", response_model=SubjectListResponse)
async def common_subjects(
    user: Annotated[User, Depends(get_current_user)],
    grade: Annotated[int, Query(ge=1, le=3)],
    semester: Annotated[int, Query(ge=1, le=2)],
    curriculum: Annotated[str | None, Query()] = None,
) -> SubjectListResponse:
    """그 학년·학기에 흔히 편성되는 과목 예시(학교마다 다르다)."""
    chosen = _curriculum(user, curriculum)
    items = subject_catalog.common_for_period(chosen, grade, semester)
    return SubjectListResponse(
        curriculum=chosen, items=[SubjectRead.model_validate(s) for s in items]
    )
