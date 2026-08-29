"""계획(plan_items) 서비스 — 두 번째 목적인 '미래를 체계적으로 계획하기'의 중심.

계획은 세 곳에서 생긴다: 학생이 탭에서 직접, AI 로드맵 생성, 후속 추천에서 골라
담기. 어느 쪽이든 완료 처리하면 item_type에 맞는 실제 기록 행으로 승격되고, 계획이
달려 있던 과거 활동이 새 활동의 parent_activity_id로 복사되어 계보가 이어진다.
"""

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidPlanTransitionError, PlanItemNotFoundError
from app.models.activity import Activity, ActivityCategory, ActivityType
from app.models.diagnosis import Diagnosis, DiagnosisStatus
from app.models.plan_item import PlanItem, PlanItemOrigin, PlanItemStatus, PlanItemType
from app.models.reading_activity import ReadingActivity
from app.models.user import User
from app.schemas.plan import (
    PlanItemCompleteRequest,
    PlanItemCreate,
    RoadmapDraft,
    RoadmapGenerateRequest,
    RoadmapSemester,
)
from app.services.llm import call_structured
from app.services.plan_prompts import ROADMAP_SYSTEM_PROMPT
from app.services.student_interest_service import get_current_interests

ALL_SEMESTERS = [(grade, semester) for grade in (1, 2, 3) for semester in (1, 2)]


async def get_plan_item(db: AsyncSession, user_id: uuid.UUID, plan_id: uuid.UUID) -> PlanItem:
    plan = await db.scalar(
        select(PlanItem).where(PlanItem.id == plan_id, PlanItem.user_id == user_id)
    )
    if plan is None:
        raise PlanItemNotFoundError("계획을 찾을 수 없습니다")
    return plan


async def create_plan_item(
    db: AsyncSession,
    user_id: uuid.UUID,
    data: PlanItemCreate,
    origin: PlanItemOrigin = PlanItemOrigin.USER,
) -> PlanItem:
    plan = PlanItem(user_id=user_id, origin=origin.value, **data.model_dump())
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


async def update_plan_item(
    db: AsyncSession, user_id: uuid.UUID, plan_id: uuid.UUID, data: dict[str, Any]
) -> PlanItem:
    plan = await get_plan_item(db, user_id, plan_id)
    for key, value in data.items():
        setattr(plan, key, value.value if hasattr(value, "value") else value)
    await db.commit()
    await db.refresh(plan)
    return plan


async def delete_plan_item(db: AsyncSession, user_id: uuid.UUID, plan_id: uuid.UUID) -> None:
    plan = await get_plan_item(db, user_id, plan_id)
    await db.delete(plan)
    await db.commit()


async def complete_plan_item(
    db: AsyncSession, user: User, plan_id: uuid.UUID, data: PlanItemCompleteRequest
) -> PlanItem:
    """계획을 실제 기록으로 승격시킨다. 활동/수행평가는 activities로, 독서는
    reading_activities로 옮겨가고, 나머지 타입은 상태만 done이 된다."""
    plan = await get_plan_item(db, user.id, plan_id)
    if plan.status == PlanItemStatus.DONE.value:
        raise InvalidPlanTransitionError("이미 완료된 계획입니다")

    grade = data.grade or plan.target_grade or user.current_grade
    semester = data.semester or plan.target_semester or user.current_semester

    if plan.item_type in (PlanItemType.ACTIVITY, PlanItemType.ASSESSMENT):
        if grade is None:
            raise InvalidPlanTransitionError(
                "활동으로 기록하려면 학년이 필요합니다 — grade를 함께 보내주세요"
            )
        default_category = (
            ActivityCategory.ASSESSMENT
            if plan.item_type == PlanItemType.ASSESSMENT
            else ActivityCategory.ETC
        )
        activity = Activity(
            user_id=user.id,
            parent_activity_id=plan.source_activity_id,
            grade=grade,
            semester=semester,
            activity_category=(data.activity_category or default_category).value,
            subject=plan.subject,
            activity_name=plan.title,
            activity_type=(data.activity_type or ActivityType.OTHER).value,
            description=data.description or plan.description or plan.title,
            keywords=plan.keywords,
        )
        db.add(activity)
        await db.flush()
        plan.completed_activity_id = activity.id

    elif plan.item_type == PlanItemType.READING:
        if grade is None:
            raise InvalidPlanTransitionError(
                "독서로 기록하려면 학년이 필요합니다 — grade를 함께 보내주세요"
            )
        reading = ReadingActivity(
            user_id=user.id,
            grade=grade,
            semester=semester,
            subject=plan.subject,
            title=plan.title,
            author=data.author,
        )
        db.add(reading)
        await db.flush()
        plan.completed_reading_id = reading.id

    plan.status = PlanItemStatus.DONE.value
    await db.commit()
    await db.refresh(plan)
    return plan


def _target_semesters(user: User, data: RoadmapGenerateRequest) -> list[tuple[int, int]]:
    """현재 학기 '다음'부터 목표 학기까지. 학년/학기를 아직 모르면 3년 전체를 대상으로
    해서, 온보딩만 마친 신입생도 로드맵을 받을 수 있게 한다."""
    if user.current_grade is None:
        start = (1, 1)
    else:
        current = (user.current_grade, user.current_semester or 1)
        after = [pair for pair in ALL_SEMESTERS if pair > current]
        start = after[0] if after else current

    until = (data.until_grade or 3, data.until_semester or 2)
    return [pair for pair in ALL_SEMESTERS if start <= pair <= until]


async def generate_roadmap(
    db: AsyncSession, user: User, data: RoadmapGenerateRequest
) -> tuple[list[RoadmapSemester], list[PlanItem]]:
    targets = _target_semesters(user, data)
    if not targets:
        return [], []

    interests = await get_current_interests(db, user.id)
    activities = list(
        await db.scalars(
            select(Activity).where(Activity.user_id == user.id).order_by(Activity.grade)
        )
    )
    existing_plans = list(
        await db.scalars(
            select(PlanItem).where(
                PlanItem.user_id == user.id, PlanItem.status != PlanItemStatus.DROPPED.value
            )
        )
    )
    diagnosis = await db.scalar(
        select(Diagnosis)
        .where(Diagnosis.user_id == user.id, Diagnosis.status == DiagnosisStatus.DONE.value)
        .order_by(Diagnosis.created_at.desc())
        .limit(1)
    )

    user_content = json.dumps(
        {
            "target_semesters": [{"grade": g, "semester": s} for g, s in targets],
            "focus": data.focus,
            "career_context": interests,
            "diagnosis": (
                {
                    "overall_summary": diagnosis.overall_summary,
                    "strengths": diagnosis.strengths,
                    "weaknesses": diagnosis.weaknesses,
                    "career_gap_analysis": diagnosis.career_gap_analysis,
                    "career_thread": diagnosis.career_thread,
                }
                if diagnosis
                else None
            ),
            "past_activities": [
                {
                    "id": str(a.id),
                    "grade": a.grade,
                    "semester": a.semester,
                    "activity_name": a.activity_name,
                    "activity_type": a.activity_type,
                    "subject": a.subject,
                    "keywords": a.keywords,
                }
                for a in activities
            ],
            "existing_plans": [
                {
                    "title": p.title,
                    "target_grade": p.target_grade,
                    "target_semester": p.target_semester,
                    "status": p.status,
                }
                for p in existing_plans
            ],
        },
        ensure_ascii=False,
    )

    draft = await call_structured(ROADMAP_SYSTEM_PROMPT, user_content, RoadmapDraft)

    if data.replace_existing:
        # 아직 손대지 않은 AI 로드맵만 지운다 — 학생이 직접 세웠거나 이미 진행 중인
        # 계획을 재생성이 삼켜버리면 안 된다.
        for plan in existing_plans:
            if (
                plan.origin == PlanItemOrigin.AI_ROADMAP.value
                and plan.status == PlanItemStatus.PLANNED.value
                and (plan.target_grade, plan.target_semester) in targets
            ):
                await db.delete(plan)

    known_activity_ids = {a.id for a in activities}
    target_set = set(targets)
    created: list[PlanItem] = []
    kept_semesters: list[RoadmapSemester] = []

    for semester_plan in draft.semesters:
        if (semester_plan.grade, semester_plan.semester) not in target_set:
            continue
        kept_semesters.append(semester_plan)
        for item in semester_plan.items:
            # LLM이 지어낸 활동 id는 버린다 — 남의 행이나 없는 행을 가리키면
            # 계보가 깨진다.
            source_activity_id = (
                item.source_activity_id if item.source_activity_id in known_activity_ids else None
            )
            plan = PlanItem(
                user_id=user.id,
                item_type=item.item_type.value,
                title=item.title,
                description=item.description,
                subject=item.subject,
                target_grade=semester_plan.grade,
                target_semester=semester_plan.semester,
                origin=PlanItemOrigin.AI_ROADMAP.value,
                source_activity_id=source_activity_id,
                keywords=item.keywords,
            )
            db.add(plan)
            created.append(plan)

    await db.commit()
    for plan in created:
        await db.refresh(plan)
    return kept_semesters, created
