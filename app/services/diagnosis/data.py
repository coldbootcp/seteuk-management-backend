import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academic_performance import AcademicPerformance
from app.models.activity import Activity
from app.models.award import Award
from app.models.reading_activity import ReadingActivity
from app.models.volunteer_record import VolunteerRecord
from app.schemas.diagnosis import (
    GradesTrend,
    GradesTrendPoint,
)

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
    """학기별 평가 섹션의 입력. 성적/독서/활동만 담는다 — 출결·봉사는 학년
    단위로만 존재해 학기 귀속이 애매하고, 진로 유기적 평가 섹션에서 따로 다룬다."""

    grade: int
    semester: int
    academic_performance: list[AcademicPerformance] = field(default_factory=list)
    reading_activities: list[ReadingActivity] = field(default_factory=list)
    activities: list[Activity] = field(default_factory=list)

    def to_prompt_json(self) -> dict[str, Any]:
        return {
            "academic_performance": [serialize_row(r) for r in self.academic_performance],
            "reading_activities": [serialize_row(r) for r in self.reading_activities],
            "activities": [serialize_row(r) for r in self.activities],
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
            )
        )
    return groups


async def get_domain_rows(db: AsyncSession, user_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
    """사전질문 생성에 쓰는 요약 — 진단 파이프라인의 학기별 평가/종합 평가와는
    다른 용도(어떤 갭을 물어봐야 할지 판단하는 재료)라 그대로 둔다."""
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


async def get_career_thread_material(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """진로 유기적 평가 섹션의 입력. 활동은 학기 유무와 무관하게 전부(계보용
    parent_activity_id 포함) 넘기고, 수상/봉사도 후보 재료로 함께 준다 — 이 중
    무엇을 사슬에 넣을지는 LLM이 진로 관련성으로 판단한다."""
    activities = await db.scalars(select(Activity).where(Activity.user_id == user_id))
    awards = await db.scalars(select(Award).where(Award.user_id == user_id))
    volunteer = await db.scalars(select(VolunteerRecord).where(VolunteerRecord.user_id == user_id))

    return {
        "activities": [serialize_row(r) for r in activities],
        "awards": [serialize_row(r) for r in awards],
        "volunteer_records": [serialize_row(r) for r in volunteer],
    }


async def get_activities_by_grade(
    db: AsyncSession, user_id: uuid.UUID
) -> dict[int, list[Activity]]:
    """활동 인벤토리 섹션의 배치 단위. 165개 같은 대량 활동을 한 호출에 몰아넣으면
    출력이 잘릴 위험이 있어 학년 단위로 나눠 호출한다."""
    activities = list(
        await db.scalars(
            select(Activity)
            .where(Activity.user_id == user_id)
            .order_by(Activity.grade, Activity.semester)
        )
    )
    by_grade: dict[int, list[Activity]] = defaultdict(list)
    for activity in activities:
        by_grade[activity.grade].append(activity)
    return dict(by_grade)




def _parse_rank(raw: str | None) -> int | None:
    """석차등급 문자열을 1~9 정수로. 생기부에는 "3"처럼 숫자만 오는 게 보통이지만
    "3/280" 같은 표기도 있어 앞의 정수만 취한다. 1~9를 벗어나면 석차등급이 아니라
    다른 값이 들어온 것으로 보고 버린다."""
    if not raw:
        return None
    match = re.match(r"\s*(\d+)", raw)
    if match is None:
        return None
    value = int(match.group(1))
    return value if 1 <= value <= 9 else None


async def compute_grades_trend(db: AsyncSession, user_id: uuid.UUID) -> GradesTrend:
    """성적 추이 섹션 — 진단에서 유일하게 LLM을 거치지 않는다.

    **학기별 평균 석차등급 한 줄만** 만든다. 석차등급이 없는 과목(진로선택·전문교과·
    P과목)은 평균에서 빼는데, 성취도 A/B/C를 등급으로 환산하면 없는 숫자를 지어내는
    것이기 때문이다. 대신 몇 개가 빠졌는지를 `excluded_count`로 함께 넘겨, 평균이
    그 학기 전체를 대표하는 것처럼 읽히지 않게 한다.
    """
    rows = list(
        await db.scalars(
            select(AcademicPerformance)
            .where(AcademicPerformance.user_id == user_id)
            .order_by(AcademicPerformance.grade, AcademicPerformance.semester)
        )
    )

    by_semester: dict[tuple[int, int], list[AcademicPerformance]] = defaultdict(list)
    for row in rows:
        by_semester[(row.grade, row.semester)].append(row)

    overall: list[GradesTrendPoint] = []
    for (grade, semester), semester_rows in sorted(by_semester.items()):
        ranks = [r for r in (_parse_rank(row.rank) for row in semester_rows) if r is not None]
        overall.append(
            GradesTrendPoint(
                grade=grade,
                semester=semester,
                average_rank=(sum(ranks) / len(ranks)) if ranks else None,
                subject_count=len(ranks),
                excluded_count=len(semester_rows) - len(ranks),
            )
        )

    return GradesTrend(overall=overall)
