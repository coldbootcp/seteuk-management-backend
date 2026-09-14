"""학생별 입학 연도 기반 교육·대입 제도 기준 API."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.education_policy import (
    AdmissionPolicyRuleRead,
    EducationPolicyRead,
    EducationPolicyResolutionRead,
)
from app.services import education_policy_service

router = APIRouter(prefix="/education-policies", tags=["education-policies"])


@router.get("/me", response_model=EducationPolicyResolutionRead)
async def resolve_my_education_policy(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EducationPolicyResolutionRead:
    """생기부 학적사항 또는 온보딩에 확정된 입학 연도로 제도를 판정한다."""
    policy = await education_policy_service.get_policy_for_freshman_year(
        db, user.freshman_academic_year
    )
    rules = await education_policy_service.get_rules_for_policy(db, policy)
    if user.freshman_academic_year is None:
        return EducationPolicyResolutionRead(
            freshman_academic_year=None,
            policy=None,
            admission_rules=[AdmissionPolicyRuleRead.model_validate(rule) for rule in rules],
            needs_freshman_academic_year=True,
            message="입학 연도를 확인하면 성적·학생부·대입 기준을 해당 학생에게 맞춰 적용합니다.",
        )
    if policy is None:
        return EducationPolicyResolutionRead(
            freshman_academic_year=user.freshman_academic_year,
            policy=None,
            admission_rules=[AdmissionPolicyRuleRead.model_validate(rule) for rule in rules],
            needs_freshman_academic_year=False,
            message="이 입학 연도의 교육 제도 기준은 아직 수집 중입니다.",
        )
    return EducationPolicyResolutionRead(
        freshman_academic_year=user.freshman_academic_year,
        policy=EducationPolicyRead.model_validate(policy),
        admission_rules=[AdmissionPolicyRuleRead.model_validate(rule) for rule in rules],
        needs_freshman_academic_year=False,
    )
