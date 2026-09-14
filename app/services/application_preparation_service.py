"""3년 활동을 자소서 설계 근거로 정리한다. 문장 생성이나 적합도 판정은 하지 않는다."""

import json
import uuid

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.activity_attachment import ActivityAttachment
from app.models.activity_thread import ActivityThread
from app.models.admission_catalog import AdmissionProgram, AdmissionTrack, University
from app.models.application_preparation import ApplicationEvidence, ApplicationPreparation
from app.schemas.application_preparation import (
    ActivityEvidenceRead,
    ActivityFlowRead,
    ApplicationPreparationCreate,
    ApplicationPreparationRead,
    ApplicationPreparationUpdate,
    PreparationActivityRecommendationRead,
    RankedActivityRead,
)
from app.services.application_preparation_prompts import ACTIVITY_RANKING_SYSTEM_PROMPT
from app.services.llm import call_structured


class _RankedActivityDraft(BaseModel):
    index: int
    reason: str


class _ActivityRankingDraft(BaseModel):
    ranked: list[_RankedActivityDraft]
    gap_notice: str | None = None


def _readiness(activity: Activity, attachment_count: int) -> tuple[str, list[str]]:
    missing: list[str] = []
    if len(activity.description.strip()) < 80:
        missing.append("무엇을 어떻게 했는지")
    if not activity.reflection or len(activity.reflection.strip()) < 40:
        missing.append("배운 점과 느낀 점")
    if attachment_count == 0:
        missing.append("보고서·발표자료 등 근거 파일")
    return ("ready" if not missing else "needs_detail", missing)


async def _activity_rows(db: AsyncSession, user_id: uuid.UUID) -> list[tuple[Activity, int]]:
    result = await db.execute(
        select(Activity, func.count(ActivityAttachment.id))
        .outerjoin(ActivityAttachment, ActivityAttachment.activity_id == Activity.id)
        .where(Activity.user_id == user_id)
        .group_by(Activity.id)
        .order_by(Activity.grade, Activity.semester.nullsfirst(), Activity.created_at)
    )
    return [(activity, count) for activity, count in result.all()]


def _evidence_read(
    activity: Activity, attachment_count: int, evidence: ApplicationEvidence | None = None
) -> ActivityEvidenceRead:
    readiness, missing = _readiness(activity, attachment_count)
    return ActivityEvidenceRead(
        activity_id=activity.id,
        grade=activity.grade,
        semester=activity.semester,
        title=activity.activity_name,
        subject=activity.subject,
        description=activity.description,
        reflection=activity.reflection,
        attachment_count=attachment_count,
        readiness=readiness,
        missing_fields=missing,
        narrative_role=evidence.narrative_role if evidence else None,
        order_index=evidence.order_index if evidence else None,
        student_note=evidence.student_note if evidence else None,
    )


async def list_activity_flows(db: AsyncSession, user_id: uuid.UUID) -> list[ActivityFlowRead]:
    rows = await _activity_rows(db, user_id)
    threads = list(
        await db.scalars(
            select(ActivityThread)
            .where(ActivityThread.user_id == user_id)
            .order_by(ActivityThread.created_at)
        )
    )
    by_thread: dict[uuid.UUID | None, list[ActivityEvidenceRead]] = {}
    for activity, attachment_count in rows:
        by_thread.setdefault(activity.thread_id, []).append(
            _evidence_read(activity, attachment_count)
        )

    flows = [
        ActivityFlowRead(
            id=thread.id,
            title=thread.title,
            description=thread.description,
            activities=by_thread.pop(thread.id, []),
        )
        for thread in threads
        if by_thread.get(thread.id)
    ]
    if unthreaded := by_thread.get(None):
        flows.append(
            ActivityFlowRead(
                id=None, title="아직 묶이지 않은 활동", description=None, activities=unthreaded
            )
        )
    return flows


async def recommend_activities_for_preparation(
    db: AsyncSession, user_id: uuid.UUID, preparation_id: uuid.UUID
) -> PreparationActivityRecommendationRead | None:
    """LLM에는 일회성 정수 index만 주고, 결과는 서버의 활동 행으로 역참조한다."""
    preparation = await db.scalar(
        select(ApplicationPreparation).where(
            ApplicationPreparation.id == preparation_id, ApplicationPreparation.user_id == user_id
        )
    )
    if preparation is None:
        return None
    program = await db.scalar(
        select(AdmissionProgram).where(AdmissionProgram.id == preparation.program_id)
    )
    university = await db.scalar(
        select(University).where(University.id == preparation.university_id)
    )
    track = (
        await db.scalar(select(AdmissionTrack).where(AdmissionTrack.id == preparation.track_id))
        if preparation.track_id
        else None
    )
    rows = await _activity_rows(db, user_id)
    if not rows:
        return PreparationActivityRecommendationRead(
            activities=[], gap_notice="먼저 실제 활동 기록을 저장하면 핵심 활동을 추릴 수 있습니다."
        )
    payload = {
        "target": {
            "university": university.name if university else "",
            "program": program.name if program else "",
            "track": track.name if track else "",
        },
        "activities": [
            {
                "index": index,
                "grade": activity.grade,
                "semester": activity.semester,
                "category": activity.activity_category,
                "subject": activity.subject,
                "title": activity.activity_name,
                "description": activity.description,
                "reflection": activity.reflection,
                "keywords": activity.keywords,
            }
            for index, (activity, _) in enumerate(rows)
        ],
    }
    draft = await call_structured(
        ACTIVITY_RANKING_SYSTEM_PROMPT,
        json.dumps(payload, ensure_ascii=False),
        _ActivityRankingDraft,
    )
    # 프롬프트 지시는 충분하지 않다. 범위를 벗어난 index·중복·빈 근거는 서버에서 제거한다.
    chosen: list[RankedActivityRead] = []
    seen: set[int] = set()
    for item in draft.ranked:
        if not 0 <= item.index < len(rows) or item.index in seen or not item.reason.strip():
            continue
        seen.add(item.index)
        activity, attachment_count = rows[item.index]
        readiness, missing = _readiness(activity, attachment_count)
        chosen.append(
            RankedActivityRead(
                activity_id=activity.id,
                rank=len(chosen) + 1,
                reason=item.reason.strip()[:300],
                readiness=readiness,
                missing_fields=missing,
            )
        )
        if len(chosen) == 5:
            break
    return PreparationActivityRecommendationRead(
        activities=chosen, gap_notice=(draft.gap_notice or None)[:500] if draft.gap_notice else None
    )


async def create_preparation(
    db: AsyncSession, user_id: uuid.UUID, data: ApplicationPreparationCreate
) -> ApplicationPreparation:
    program = await db.scalar(
        select(AdmissionProgram).where(AdmissionProgram.id == data.program_id)
    )
    if program is None or program.university_id != data.university_id:
        raise ValueError("선택한 대학과 모집단위의 연결이 맞지 않습니다.")
    if data.track_id is not None:
        track = await db.scalar(select(AdmissionTrack).where(AdmissionTrack.id == data.track_id))
        if track is None or track.program_id != program.id:
            raise ValueError("선택한 모집단위와 전형의 연결이 맞지 않습니다.")
    entry = ApplicationPreparation(user_id=user_id, **data.model_dump())
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def update_preparation(
    db: AsyncSession,
    user_id: uuid.UUID,
    preparation_id: uuid.UUID,
    data: ApplicationPreparationUpdate,
) -> ApplicationPreparation | None:
    entry = await db.scalar(
        select(ApplicationPreparation).where(
            ApplicationPreparation.id == preparation_id, ApplicationPreparation.user_id == user_id
        )
    )
    if entry is None:
        return None
    activity_ids = [item.activity_id for item in data.evidence]
    owned = (
        set(
            await db.scalars(
                select(Activity.id).where(
                    Activity.user_id == user_id, Activity.id.in_(activity_ids)
                )
            )
        )
        if activity_ids
        else set()
    )
    if len(owned) != len(set(activity_ids)):
        raise ValueError("내 활동만 지원 근거로 선택할 수 있습니다.")
    entry.central_question = data.central_question
    entry.narrative_outline = data.narrative_outline
    existing = list(
        await db.scalars(
            select(ApplicationEvidence).where(ApplicationEvidence.preparation_id == entry.id)
        )
    )
    for evidence in existing:
        await db.delete(evidence)
    for item in data.evidence:
        db.add(ApplicationEvidence(preparation_id=entry.id, **item.model_dump()))
    await db.commit()
    await db.refresh(entry)
    return entry


async def delete_preparation(
    db: AsyncSession, user_id: uuid.UUID, preparation_id: uuid.UUID
) -> bool:
    entry = await db.scalar(
        select(ApplicationPreparation).where(
            ApplicationPreparation.id == preparation_id, ApplicationPreparation.user_id == user_id
        )
    )
    if entry is None:
        return False
    await db.delete(entry)
    await db.commit()
    return True


async def read_preparation(
    db: AsyncSession, user_id: uuid.UUID, preparation: ApplicationPreparation
) -> ApplicationPreparationRead:
    university = await db.scalar(
        select(University).where(University.id == preparation.university_id)
    )
    program = await db.scalar(
        select(AdmissionProgram).where(AdmissionProgram.id == preparation.program_id)
    )
    track = (
        await db.scalar(select(AdmissionTrack).where(AdmissionTrack.id == preparation.track_id))
        if preparation.track_id
        else None
    )
    rows = await _activity_rows(db, user_id)
    evidence_by_activity = {
        item.activity_id: item
        for item in await db.scalars(
            select(ApplicationEvidence).where(ApplicationEvidence.preparation_id == preparation.id)
        )
    }
    evidence = [
        _evidence_read(activity, count, evidence_by_activity[activity.id])
        for activity, count in rows
        if activity.id in evidence_by_activity
    ]
    evidence.sort(key=lambda item: item.order_index or 0)
    return ApplicationPreparationRead(
        id=preparation.id,
        university_id=preparation.university_id,
        program_id=preparation.program_id,
        track_id=preparation.track_id,
        university_name=university.name if university else "",
        program_name=program.name if program else "",
        track_name=track.name if track else None,
        admission_year=preparation.admission_year,
        central_question=preparation.central_question,
        narrative_outline=preparation.narrative_outline,
        evidence=evidence,
        created_at=preparation.created_at,
        updated_at=preparation.updated_at,
    )
