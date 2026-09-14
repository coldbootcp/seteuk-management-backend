"""입학 연도 기준 제도 판정과 성적 입력 보호 규칙."""

import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import GradeScaleMismatchError
from app.models.education_policy import AdmissionPolicyRule, EducationPolicy
from app.models.user import User


async def get_policy_for_freshman_year(
    db: AsyncSession, freshman_academic_year: int | None
) -> EducationPolicy | None:
    """입학 연도에 맞는 단 하나의 정책을 찾는다.

    오늘 날짜나 현재 학년으로 추측하지 않는다. 졸업생이 과거 생기부를 올리는
    경우에도 같은 문서 기준을 적용해야 하기 때문이다.
    """
    if freshman_academic_year is None:
        return None
    return await db.scalar(
        select(EducationPolicy)
        .where(
            EducationPolicy.freshman_year_start <= freshman_academic_year,
            or_(
                EducationPolicy.freshman_year_end.is_(None),
                EducationPolicy.freshman_year_end >= freshman_academic_year,
            ),
        )
        .order_by(EducationPolicy.freshman_year_start.desc())
        .limit(1)
    )


async def get_rules_for_policy(
    db: AsyncSession, policy: EducationPolicy | None
) -> list[AdmissionPolicyRule]:
    """정책별 기준과 모든 학생에게 공통으로 적용되는 기준을 함께 읽는다."""
    policy_filter = (
        AdmissionPolicyRule.policy_id.is_(None)
        if policy is None
        else or_(
            AdmissionPolicyRule.policy_id.is_(None),
            AdmissionPolicyRule.policy_id == policy.id,
        )
    )
    rows = await db.scalars(
        select(AdmissionPolicyRule)
        .where(policy_filter)
        .order_by(AdmissionPolicyRule.category.asc(), AdmissionPolicyRule.title.asc())
    )
    return list(rows)


def _numeric_rank(rank: str | None) -> int | None:
    """숫자로 확정된 석차등급만 검증한다.

    생기부 원문에 드물게 등장하는 비수치 표기는 데이터 손실 없이 보존하되, 수기
    입력 화면이 보낼 수 있는 숫자 등급에는 반드시 한도를 적용한다.
    """
    if rank is None:
        return None
    value = rank.strip()
    return int(value) if re.fullmatch(r"\d+", value) else None


async def validate_rank_for_user(
    db: AsyncSession, user: User, rank: str | None
) -> None:
    """등급 체계와 맞지 않는 수기 성적이 저장되는 것을 서버에서도 막는다."""
    numeric_rank = _numeric_rank(rank)
    if numeric_rank is None:
        return
    if not 1 <= numeric_rank <= 9:
        raise GradeScaleMismatchError(
            "석차등급은 1~9 사이의 숫자로 입력해 주세요.",
            extra={"rank": numeric_rank},
        )
    policy = await get_policy_for_freshman_year(db, user.freshman_academic_year)
    if policy and policy.rank_grade_scale and numeric_rank > policy.rank_grade_scale:
        raise GradeScaleMismatchError(
            f"{user.freshman_academic_year}학년도 입학생에게 적용되는 "
            f"{policy.rank_grade_scale}등급제에서는 {numeric_rank}등급을 입력할 수 없습니다.",
            extra={
                "rank": numeric_rank,
                "rank_grade_scale": policy.rank_grade_scale,
                "policy_code": policy.code,
            },
        )
