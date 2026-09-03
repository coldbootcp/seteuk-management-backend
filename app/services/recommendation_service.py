"""기능2 — 이전 활동 기반 후속 탐구 추천.

범용 LLM과의 차별점이 여기 있으므로, 프롬프트에 활동 한 건만 던지지 않고 그 활동이
속한 계보 사슬 전체와 진단 결과를 함께 넘긴다. 진단(3단계, 비동기 job)과 달리 LLM
호출이 한 번이라 동기로 처리하고 결과를 바로 돌려준다.
"""

import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ActivityNotFoundError, RecommendationNotFoundError
from app.models.activity import Activity
from app.models.diagnosis import Diagnosis, DiagnosisStatus
from app.models.plan_item import PlanItem, PlanItemOrigin, PlanItemStatus
from app.models.recommendation import Recommendation
from app.models.recommendation_feedback import RecommendationFeedback
from app.models.user import User
from app.schemas.recommendation import (
    AdoptOptionRequest,
    FollowUpRequest,
    RecommendationDraft,
)
from app.services.activity_lineage_service import get_lineage
from app.services.llm import call_structured
from app.services.recommendation_prompts import FOLLOW_UP_SYSTEM_PROMPT
from app.services.student_interest_service import get_current_interests


async def create_follow_up(
    db: AsyncSession, user: User, data: FollowUpRequest
) -> Recommendation:
    activity = await db.scalar(
        select(Activity).where(
            Activity.id == data.source_activity_id, Activity.user_id == user.id
        )
    )
    if activity is None:
        raise ActivityNotFoundError("활동을 찾을 수 없습니다")

    lineage = await get_lineage(db, user.id, activity.id)
    interests = await get_current_interests(db, user.id)
    diagnosis = await db.scalar(
        select(Diagnosis)
        .where(Diagnosis.user_id == user.id, Diagnosis.status == DiagnosisStatus.DONE.value)
        .order_by(Diagnosis.created_at.desc())
        .limit(1)
    )

    user_content = json.dumps(
        {
            "source_activity": {
                "grade": activity.grade,
                "semester": activity.semester,
                "activity_category": activity.activity_category,
                "subject": activity.subject,
                "activity_name": activity.activity_name,
                "activity_type": activity.activity_type,
                "role": activity.role,
                "description": activity.description,
                "keywords": activity.keywords,
            },
            "lineage": [
                {
                    "kind": n.kind,
                    "title": n.title,
                    "grade": n.grade,
                    "semester": n.semester,
                    "status": n.status,
                }
                for n in lineage
            ],
            "desired_activity_type": (
                data.desired_activity_type.value if data.desired_activity_type else None
            ),
            "student_note": data.note,
            "career_context": interests,
            "current_grade": user.current_grade,
            "current_semester": user.current_semester,
            "diagnosis": (
                {
                    "strengths": diagnosis.strengths,
                    "weaknesses": diagnosis.weaknesses,
                    "opportunities": diagnosis.opportunities,
                    "threats": diagnosis.threats,
                }
                if diagnosis
                else None
            ),
        },
        ensure_ascii=False,
    )

    draft = await call_structured(FOLLOW_UP_SYSTEM_PROMPT, user_content, RecommendationDraft)

    recommendation = Recommendation(
        user_id=user.id,
        source_activity_id=activity.id,
        desired_activity_type=(
            data.desired_activity_type.value if data.desired_activity_type else None
        ),
        options=[option.model_dump() for option in draft.options],
    )
    db.add(recommendation)
    await db.commit()
    await db.refresh(recommendation)
    return recommendation


async def get_recommendation(
    db: AsyncSession, user_id: uuid.UUID, recommendation_id: uuid.UUID
) -> Recommendation:
    recommendation = await db.scalar(
        select(Recommendation).where(
            Recommendation.id == recommendation_id, Recommendation.user_id == user_id
        )
    )
    if recommendation is None:
        raise RecommendationNotFoundError("추천 결과를 찾을 수 없습니다")
    return recommendation


async def adopt_option(
    db: AsyncSession, user: User, recommendation_id: uuid.UUID, data: AdoptOptionRequest
) -> PlanItem:
    """추천 선택지 하나를 계획으로 담는다. 계획은 추천의 출처 활동을 그대로 물려받아,
    나중에 완료 처리하면 그 활동의 자식으로 기록된다."""
    recommendation = await get_recommendation(db, user.id, recommendation_id)
    if not 0 <= data.option_index < len(recommendation.options):
        raise RecommendationNotFoundError("해당 선택지를 찾을 수 없습니다")

    option = recommendation.options[data.option_index]
    plan = PlanItem(
        user_id=user.id,
        item_type=data.item_type.value,
        title=option["topic"],
        description=option["expected_output"],
        target_grade=data.target_grade or user.current_grade,
        target_semester=data.target_semester or user.current_semester,
        status=PlanItemStatus.PLANNED.value,
        origin=PlanItemOrigin.RECOMMENDATION.value,
        source_activity_id=recommendation.source_activity_id,
        source_recommendation_id=recommendation.id,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


# --- 추천 피드백 — append-only 개인화 신호 ---


async def record_feedback(
    db: AsyncSession,
    user_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    option_index: int,
    action: str,
    reason: str | None,
) -> RecommendationFeedback:
    """선택지에 대한 반응을 남긴다.

    같은 선택지에 대해 마음이 바뀌어도 이전 기록을 고치지 않고 새 행을 쌓는다 —
    "저장했다가 나중에 거절했다"는 것 자체가 신호이기 때문이다. 최신 의견이 필요한
    화면은 created_at으로 마지막 것을 읽으면 된다.
    """
    recommendation = await get_recommendation(db, user_id, recommendation_id)
    if not 0 <= option_index < len(recommendation.options):
        raise RecommendationNotFoundError("해당 선택지를 찾을 수 없습니다")

    feedback = RecommendationFeedback(
        user_id=user_id,
        recommendation_id=recommendation_id,
        option_index=option_index,
        action=action,
        reason=reason,
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)
    return feedback


async def list_feedback(
    db: AsyncSession, user_id: uuid.UUID, limit: int = 200
) -> list[RecommendationFeedback]:
    rows = await db.scalars(
        select(RecommendationFeedback)
        .where(RecommendationFeedback.user_id == user_id)
        .order_by(RecommendationFeedback.created_at.desc())
        .limit(limit)
    )
    return list(rows)
