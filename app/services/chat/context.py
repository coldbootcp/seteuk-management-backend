"""챗봇 개인화의 재료 — '세특 메모리' 조립.

챗봇은 이 사용자에 대해 아는 것을 전부 시스템 프롬프트에 싣고 시작한다. 다만 3년치
기록을 통째로 넣으면 컨텍스트가 터지므로, 각 영역마다 상한을 두고 최신 학년부터
채운다. 상한에 걸려 잘린 영역은 counts에 전체 개수가 남아 있어, 챗봇이 "기록이 더
있다"는 사실 자체는 알 수 있다.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academic_performance import AcademicPerformance
from app.models.activity import Activity
from app.models.attendance import Attendance
from app.models.award import Award
from app.models.diagnosis import Diagnosis, DiagnosisStatus
from app.models.plan_item import PlanItem, PlanItemStatus
from app.models.reading_activity import ReadingActivity
from app.models.user import User
from app.models.volunteer_record import VolunteerRecord
from app.services.student_interest_service import get_current_interests

MAX_ACTIVITIES = 80
MAX_READINGS = 40
MAX_AWARDS = 30
MAX_VOLUNTEER = 20
MAX_GRADES = 60
MAX_PLANS = 40
# 활동 설명은 원문이 길어 그대로 실으면 컨텍스트를 잡아먹는다.
DESCRIPTION_LIMIT = 300


def _truncate(text: str | None, limit: int = DESCRIPTION_LIMIT) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[:limit] + "…"


async def _count(db: AsyncSession, model: Any, user_id: uuid.UUID) -> int:
    return await db.scalar(
        select(func.count()).select_from(model).where(model.user_id == user_id)
    ) or 0


async def build_context(db: AsyncSession, user: User) -> dict[str, Any]:
    interests = await get_current_interests(db, user.id)

    activities = list(
        await db.scalars(
            select(Activity)
            .where(Activity.user_id == user.id)
            .order_by(Activity.grade.desc(), Activity.semester.desc().nullslast())
            .limit(MAX_ACTIVITIES)
        )
    )
    readings = list(
        await db.scalars(
            select(ReadingActivity)
            .where(ReadingActivity.user_id == user.id)
            .order_by(ReadingActivity.grade.desc())
            .limit(MAX_READINGS)
        )
    )
    grades = list(
        await db.scalars(
            select(AcademicPerformance)
            .where(AcademicPerformance.user_id == user.id)
            .order_by(AcademicPerformance.grade.desc(), AcademicPerformance.semester.desc())
            .limit(MAX_GRADES)
        )
    )
    awards = list(
        await db.scalars(
            select(Award).where(Award.user_id == user.id).limit(MAX_AWARDS)
        )
    )
    volunteer = list(
        await db.scalars(
            select(VolunteerRecord).where(VolunteerRecord.user_id == user.id).limit(MAX_VOLUNTEER)
        )
    )
    attendance = list(
        await db.scalars(select(Attendance).where(Attendance.user_id == user.id))
    )
    plans = list(
        await db.scalars(
            select(PlanItem)
            .where(
                PlanItem.user_id == user.id,
                PlanItem.status.in_(
                    [PlanItemStatus.PLANNED.value, PlanItemStatus.IN_PROGRESS.value]
                ),
            )
            .order_by(PlanItem.target_grade.asc().nullslast())
            .limit(MAX_PLANS)
        )
    )
    diagnosis = await db.scalar(
        select(Diagnosis)
        .where(Diagnosis.user_id == user.id, Diagnosis.status == DiagnosisStatus.DONE.value)
        .order_by(Diagnosis.created_at.desc())
        .limit(1)
    )

    return {
        "student": {
            "name": user.name,
            "current_grade": user.current_grade,
            "current_semester": user.current_semester,
        },
        # 학생이 직접 말해준 것들 — 챗봇이 '수정' 모드에서 갱신하는 장기 메모리.
        "memory": interests,
        "diagnosis": (
            {
                "overall_summary": diagnosis.overall_summary,
                "strengths": diagnosis.strengths,
                "weaknesses": diagnosis.weaknesses,
                "career_gap_analysis": diagnosis.career_gap_analysis,
                "career_thread": diagnosis.career_thread,
                "keyword_map": diagnosis.keyword_map,
                "created_at": diagnosis.created_at.isoformat(),
            }
            if diagnosis
            else None
        ),
        "activities": [
            {
                "id": str(a.id),
                "grade": a.grade,
                "semester": a.semester,
                "category": a.activity_category,
                "subject": a.subject,
                "name": a.activity_name,
                "type": a.activity_type,
                "description": _truncate(a.description),
                "keywords": a.keywords,
                "parent_activity_id": str(a.parent_activity_id) if a.parent_activity_id else None,
            }
            for a in activities
        ],
        "academic_performance": [
            {
                "grade": g.grade,
                "semester": g.semester,
                "subject": g.subject,
                "achievement_grade": g.achievement_grade,
                "raw_score": g.raw_score,
                "rank": g.rank,
            }
            for g in grades
        ],
        "readings": [
            {"grade": r.grade, "semester": r.semester, "title": r.title, "author": r.author}
            for r in readings
        ],
        "awards": [{"name": a.name, "rank": a.rank, "date": a.date.isoformat() if a.date else None}
                   for a in awards],
        "volunteer_records": [
            {"grade": v.grade, "place": v.place, "content": v.content, "hours": v.hours}
            for v in volunteer
        ],
        "attendance": [
            {"grade": a.grade, "total_days": a.total_days, "absence": a.absence, "note": a.note}
            for a in attendance
        ],
        "plans": [
            {
                "id": str(p.id),
                "item_type": p.item_type,
                "title": p.title,
                "target_grade": p.target_grade,
                "target_semester": p.target_semester,
                "status": p.status,
                "origin": p.origin,
            }
            for p in plans
        ],
        # 상한에 걸려 잘렸는지 챗봇이 알 수 있도록 전체 개수를 함께 준다.
        "counts": {
            "activities": await _count(db, Activity, user.id),
            "readings": await _count(db, ReadingActivity, user.id),
            "academic_performance": await _count(db, AcademicPerformance, user.id),
            "awards": await _count(db, Award, user.id),
            "volunteer_records": await _count(db, VolunteerRecord, user.id),
            "plans": await _count(db, PlanItem, user.id),
        },
    }
