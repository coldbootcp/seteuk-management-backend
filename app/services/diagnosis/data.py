import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academic_performance import AcademicPerformance
from app.models.activity import Activity
from app.models.attendance import Attendance
from app.models.award import Award
from app.models.reading_activity import ReadingActivity
from app.models.volunteer_record import VolunteerRecord

_EXCLUDED_COLUMNS = {"id", "user_id", "source_upload_id", "created_at"}


def serialize_row(row: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in row.__table__.columns:
        if column.name in _EXCLUDED_COLUMNS:
            continue
        value = getattr(row, column.name)
        if isinstance(value, datetime | date):
            value = value.isoformat()
        elif isinstance(value, uuid.UUID):
            # parent_activity_id처럼 본문에 남는 UUID 컬럼이 있어서 그대로 두면
            # json.dumps가 터진다. 문자열로 바꿔 두면 LLM이 두 활동이 같은
            # 사슬에 있다는 것 정도는 알아볼 수 있다.
            value = str(value)
        result[column.name] = value
    return result


@dataclass
class SemesterGroup:
    grade: int
    semester: int
    academic_performance: list[AcademicPerformance] = field(default_factory=list)
    reading_activities: list[ReadingActivity] = field(default_factory=list)
    activities: list[Activity] = field(default_factory=list)
    # 학년 단위로만 존재하는 데이터 — 참고용 맥락으로만 포함, 학기 귀속은 하지 않음.
    attendance: list[Attendance] = field(default_factory=list)
    volunteer_records: list[VolunteerRecord] = field(default_factory=list)

    def to_prompt_json(self) -> dict[str, Any]:
        return {
            "academic_performance": [serialize_row(r) for r in self.academic_performance],
            "reading_activities": [serialize_row(r) for r in self.reading_activities],
            "activities": [serialize_row(r) for r in self.activities],
            "attendance": [serialize_row(r) for r in self.attendance],
            "volunteer_records": [serialize_row(r) for r in self.volunteer_records],
        }


async def get_semester_groups(db: AsyncSession, user_id: uuid.UUID) -> list[SemesterGroup]:
    academic = list(
        await db.scalars(select(AcademicPerformance).where(AcademicPerformance.user_id == user_id))
    )
    reading = list(
        await db.scalars(
            select(ReadingActivity).where(
                ReadingActivity.user_id == user_id, ReadingActivity.semester.is_not(None)
            )
        )
    )
    activities = list(
        await db.scalars(
            select(Activity).where(Activity.user_id == user_id, Activity.semester.is_not(None))
        )
    )
    attendance = list(await db.scalars(select(Attendance).where(Attendance.user_id == user_id)))
    volunteer = list(
        await db.scalars(select(VolunteerRecord).where(VolunteerRecord.user_id == user_id))
    )

    all_rows = (*academic, *reading, *activities)
    pairs: set[tuple[int, int]] = {(r.grade, r.semester) for r in all_rows}

    groups: list[SemesterGroup] = []
    for grade, semester in sorted(pairs):
        groups.append(
            SemesterGroup(
                grade=grade,
                semester=semester,
                academic_performance=[
                    r for r in academic if r.grade == grade and r.semester == semester
                ],
                reading_activities=[
                    r for r in reading if r.grade == grade and r.semester == semester
                ],
                activities=[r for r in activities if r.grade == grade and r.semester == semester],
                attendance=[r for r in attendance if r.grade == grade],
                volunteer_records=[r for r in volunteer if r.grade == grade],
            )
        )
    return groups


async def get_domain_rows(db: AsyncSession, user_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
    academic = await db.scalars(
        select(AcademicPerformance).where(AcademicPerformance.user_id == user_id)
    )
    activities = await db.scalars(select(Activity).where(Activity.user_id == user_id))
    awards = await db.scalars(select(Award).where(Award.user_id == user_id))
    volunteer = await db.scalars(select(VolunteerRecord).where(VolunteerRecord.user_id == user_id))
    reading = await db.scalars(select(ReadingActivity).where(ReadingActivity.user_id == user_id))

    return {
        "성적": [serialize_row(r) for r in academic],
        "활동": [serialize_row(r) for r in activities],
        "수상": [serialize_row(r) for r in awards],
        "봉사": [serialize_row(r) for r in volunteer],
        "독서": [serialize_row(r) for r in reading],
    }
