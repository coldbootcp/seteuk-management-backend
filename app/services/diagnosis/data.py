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
    GradesTrendOverallPoint,
    GradesTrendPoint,
    GradesTrendSubject,
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


@dataclass
class FusionCandidate:
    """지식 그래프 섹션의 후보 쌍. 이미 parent_activity_id로 이어진 쌍은 진로
    유기적 평가가 이미 다루므로 후보에서 뺀다."""

    activity_a: Activity
    activity_b: Activity
    shared_keywords: list[str]
    same_subject: bool

    def to_prompt_json(self) -> dict[str, Any]:
        def _brief(activity: Activity) -> dict[str, Any]:
            description = activity.description or ""
            return {
                "id": str(activity.id),
                "grade": activity.grade,
                "semester": activity.semester,
                "subject": activity.subject,
                "activity_name": activity.activity_name,
                "description": description[:150],
                "keywords": activity.keywords,
            }

        return {
            "activity_a": _brief(self.activity_a),
            "activity_b": _brief(self.activity_b),
            "shared_keywords": self.shared_keywords,
            "same_subject": self.same_subject,
        }


def generate_fusion_candidates(
    activities: list[Activity], max_candidates: int = 60
) -> list[FusionCandidate]:
    """과목/키워드 겹침으로 후보 쌍을 결정론적으로 추린다 — LLM은 이 후보들 중
    실제로 의미 있는 것만 확정하고 라벨을 붙이는 역할만 한다."""
    linked_pairs = {
        frozenset({a.id, a.parent_activity_id}) for a in activities if a.parent_activity_id
    }

    candidates: list[FusionCandidate] = []
    for i, a in enumerate(activities):
        for b in activities[i + 1 :]:
            if frozenset({a.id, b.id}) in linked_pairs:
                continue
            same_subject = (
                bool(a.subject)
                and a.subject == b.subject
                and (a.grade, a.semester or 0) != (b.grade, b.semester or 0)
            )
            shared = sorted(set(a.keywords) & set(b.keywords))
            if not same_subject and not shared:
                continue
            candidates.append(FusionCandidate(a, b, shared, same_subject))

    candidates.sort(
        key=lambda c: len(c.shared_keywords) + (2 if c.same_subject else 0), reverse=True
    )
    return candidates[:max_candidates]


async def compute_grades_trend(db: AsyncSession, user_id: uuid.UUID) -> GradesTrend:
    """성적 추이 섹션 — LLM을 거치지 않는다. 원자료를 과목별 시계열과 학기별
    평균으로 재구성만 한다."""
    rows = list(
        await db.scalars(
            select(AcademicPerformance)
            .where(AcademicPerformance.user_id == user_id)
            .order_by(AcademicPerformance.grade, AcademicPerformance.semester)
        )
    )

    by_subject: dict[str, list[AcademicPerformance]] = defaultdict(list)
    by_semester: dict[tuple[int, int], list[AcademicPerformance]] = defaultdict(list)
    for row in rows:
        by_subject[row.subject].append(row)
        by_semester[(row.grade, row.semester)].append(row)

    subjects = [
        GradesTrendSubject(
            subject=subject,
            category=subject_rows[0].category,
            points=[
                GradesTrendPoint(
                    grade=r.grade,
                    semester=r.semester,
                    achievement_grade=r.achievement_grade,
                    raw_score=r.raw_score,
                    subject_average=r.subject_average,
                    std_deviation=r.std_deviation,
                    rank=r.rank,
                )
                for r in subject_rows
            ],
        )
        for subject, subject_rows in by_subject.items()
    ]

    overall = [
        GradesTrendOverallPoint(
            grade=grade,
            semester=semester,
            average_raw_score=(
                sum(r.raw_score for r in semester_rows if r.raw_score is not None)
                / len([r for r in semester_rows if r.raw_score is not None])
                if any(r.raw_score is not None for r in semester_rows)
                else None
            ),
            subject_count=len(semester_rows),
        )
        for (grade, semester), semester_rows in sorted(by_semester.items())
    ]

    return GradesTrend(subjects=subjects, overall=overall)
