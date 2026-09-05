"""활동 질적 검토.

정합 판정(`reconciliation_logs`)과 다른 것을 답한다. 정합은 "이 활동이 마디를
충족했는가"를 기계적으로 채점해 로드맵 진척을 옮기고, 검토는 "무엇이 근거로 남았고
무엇이 비었고 다음에 무엇을 하면 되는가"를 말해 학생에게 다음 한 걸음을 준다.
"""

import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.activity_review import ActivityReview
from app.models.roadmap import RoadmapNode
from app.schemas.roadmap import ActivityReviewDraft
from app.services.llm import call_structured
from app.services.onboarding_prompts import ACTIVITY_REVIEW_SYSTEM_PROMPT
from app.services.record_service import get_record


async def review_activity(
    db: AsyncSession, user_id: uuid.UUID, activity_id: uuid.UUID
) -> ActivityReview:
    """활동 하나를 검토해 기록으로 남긴다. 덮어쓰지 않고 쌓는다 — 활동을 고친 뒤 다시
    검토하면 이전 판단도 남아 있어야 무엇이 달라졌는지 볼 수 있다."""
    activity = await get_record(db, Activity, user_id, activity_id)

    # 같은 학기의 마디가 있으면 그 목표를 기준으로 본다. 없으면 활동 자체만 평가한다.
    node = await db.scalar(
        select(RoadmapNode)
        .where(
            RoadmapNode.user_id == user_id,
            RoadmapNode.grade == activity.grade,
            RoadmapNode.semester == activity.semester,
        )
        .order_by(RoadmapNode.updated_at.desc())
        .limit(1)
    )

    draft = await call_structured(
        ACTIVITY_REVIEW_SYSTEM_PROMPT,
        json.dumps(
            {
                "activity": {
                    "grade": activity.grade,
                    "semester": activity.semester,
                    "category": activity.activity_category,
                    "subject": activity.subject,
                    "activity_name": activity.activity_name,
                    "activity_type": activity.activity_type,
                    "role": activity.role,
                    "description": activity.description,
                    "keywords": activity.keywords,
                },
                "roadmap_node": (
                    {
                        "narrative_stage": node.narrative_stage,
                        "title": node.title,
                        "objective": node.objective,
                        "competency_goals": node.competency_goals,
                    }
                    if node
                    else None
                ),
            },
            ensure_ascii=False,
        ),
        ActivityReviewDraft,
    )

    review = ActivityReview(
        user_id=user_id,
        activity_id=activity.id,
        roadmap_node_id=node.id if node else None,
        alignment=draft.alignment,
        summary=draft.summary,
        evidence=draft.evidence,
        gaps=draft.gaps,
        next_steps=draft.next_steps,
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)
    return review


async def list_reviews(
    db: AsyncSession, user_id: uuid.UUID, limit: int = 200
) -> list[ActivityReview]:
    """활동별 **가장 최근** 검토만 돌려준다. 이력은 남아 있지만 화면이 보여주는 것은
    지금의 판단이다."""
    rows = list(
        await db.scalars(
            select(ActivityReview)
            .where(ActivityReview.user_id == user_id)
            .order_by(ActivityReview.created_at.desc())
            .limit(limit)
        )
    )
    latest: dict[uuid.UUID, ActivityReview] = {}
    for row in rows:
        latest.setdefault(row.activity_id, row)
    return list(latest.values())
