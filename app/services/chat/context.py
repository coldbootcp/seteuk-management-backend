"""챗봇 개인화의 재료 — '세특 메모리' 조립.

챗봇은 이 사용자에 대해 아는 것을 전부 시스템 프롬프트에 싣고 시작한다. 다만 3년치
기록을 통째로 넣으면 컨텍스트가 터지므로, 각 영역마다 상한을 두고 최신 학년부터
채운다. 상한에 걸려 잘린 영역은 counts에 전체 개수가 남아 있어, 챗봇이 "기록이 더
있다"는 사실 자체는 알 수 있다.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academic_performance import AcademicPerformance
from app.models.activity import Activity
from app.models.attendance import Attendance
from app.models.award import Award
from app.models.calendar_event import CalendarEvent
from app.models.diagnosis import Diagnosis, DiagnosisStatus
from app.models.plan_item import PlanItem, PlanItemStatus
from app.models.reading_activity import ReadingActivity
from app.models.seteuk_upload import SeteukUpload, UploadStatus
from app.models.timetable import Timetable
from app.models.user import User
from app.models.volunteer_record import VolunteerRecord
from app.services.academic_timing import get_academic_timing
from app.services.diagnosis.data import has_diagnosis_evidence
from app.services.student_interest_service import get_current_interests
from app.services.subject_catalog import get_subject
from app.services.subject_contents import get_content

MAX_ACTIVITIES = 80
MAX_READINGS = 40
MAX_AWARDS = 30
MAX_VOLUNTEER = 20
MAX_GRADES = 60
MAX_PLANS = 40
# 활동 설명은 원문이 길어 그대로 실으면 컨텍스트를 잡아먹는다.
DESCRIPTION_LIMIT = 300


@dataclass
class ChatReferenceCatalog:
    """한 번의 챗봇 호출 안에서만 유효한 기록 참조표.

    모델에는 데이터베이스 UUID를 절대 보내지 않는다. 모델이 선택한 작은 정수 번호를
    이 표로만 역참조해 실제 행을 찾는다. 다음 호출에서는 새 표를 만들므로, 번호는
    장기 식별자도 아니고 학생 화면에 노출되는 id도 아니다.
    """

    by_index: dict[int, tuple[str, uuid.UUID]] = field(default_factory=dict)
    _next_index: int = 1

    def register(self, kind: str, record_id: uuid.UUID) -> int:
        index = self._next_index
        self._next_index += 1
        self.by_index[index] = (kind, record_id)
        return index

    def resolve(self, index: Any, expected_kind: str) -> uuid.UUID | None:
        # bool은 Python에서 int의 하위형이므로 엄격히 배제한다.
        if isinstance(index, bool) or not isinstance(index, int):
            return None
        reference = self.by_index.get(index)
        if reference is None or reference[0] != expected_kind:
            return None
        return reference[1]


def _truncate(text: str | None, limit: int = DESCRIPTION_LIMIT) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[:limit] + "…"


def _course_entry(subject: str, category: str | None, subject_code: str | None) -> dict[str, Any]:
    """이번 학기 수강 과목 한 줄. 카탈로그 과목이면 교육과정과 공식 단원 요약을 붙여,
    챗봇이 과목 이름만 보고 내용을 짐작하지 않게 한다."""
    entry: dict[str, Any] = {
        "subject": subject,
        "category": category,
        "from_catalog": subject_code is not None,
    }
    catalog_subject = get_subject(subject_code)
    if catalog_subject is not None:
        entry["curriculum"] = f"{catalog_subject.curriculum} 개정"
        entry["course_type"] = catalog_subject.category
    content = get_content(subject_code)
    if content is not None:
        entry["content"] = {"summary": content.summary, "units": list(content.units)}
    return entry


async def _count(db: AsyncSession, model: Any, user_id: uuid.UUID) -> int:
    return await db.scalar(
        select(func.count()).select_from(model).where(model.user_id == user_id)
    ) or 0


async def _build_school_record_coverage(
    db: AsyncSession, user_id: uuid.UUID
) -> dict[str, Any]:
    """학생부 PDF가 없는 상태와, 학생부에서 읽은 기록이 없는 상태를 구분한다.

    활동 행이 0건이라는 사실만으로는 학생이 활동을 하지 않았다는 결론을 낼 수 없다.
    PDF를 올리지 않았거나 파싱·반영을 끝내지 않은 경우에는 챗봇이 '없다'가 아니라
    '확인할 수 없다'고 말할 수 있게 이 상태를 별도로 전달한다.
    """
    uploads = list(
        await db.scalars(
            select(SeteukUpload)
            .where(SeteukUpload.user_id == user_id)
            .order_by(SeteukUpload.created_at.desc())
        )
    )
    if not uploads:
        return {
            "status": "not_uploaded",
            "summary": (
                "학생부 PDF가 아직 업로드되지 않았습니다. 저장된 활동이 없더라도 "
                "이전 활동이 없었다고 판단할 수 없습니다."
            ),
        }

    latest = uploads[0]
    if latest.status == UploadStatus.PROCESSING.value:
        return {
            "status": "processing",
            "summary": (
                "가장 최근 학생부 PDF를 처리 중입니다. 이전 활동의 존재 여부를 "
                "확정적으로 말할 수 없습니다."
            ),
        }
    if latest.status == UploadStatus.FAILED.value:
        return {
            "status": "failed",
            "summary": (
                "가장 최근 학생부 PDF 처리에 실패했습니다. 저장된 활동이 없더라도 "
                "이전 활동이 없었다고 판단할 수 없습니다."
            ),
        }
    if latest.imported_at is None:
        return {
            "status": "awaiting_import",
            "summary": (
                "학생부 PDF는 읽었지만 학생이 아직 파싱 결과를 기록에 반영하지 "
                "않았습니다. 이전 활동의 존재 여부를 확정적으로 말할 수 없습니다."
            ),
        }

    return {
        "status": "imported",
        "summary": (
            "학생부 PDF의 파싱 결과가 기록에 반영되었습니다. 다만 특정 주제의 "
            "기록 부재는 '학생부에서 해당 근거를 찾지 못함'으로만 표현해야 합니다."
        ),
    }


async def build_context(db: AsyncSession, user: User) -> dict[str, Any]:
    interests = await get_current_interests(db, user.id)
    school_record_coverage = await _build_school_record_coverage(db, user.id)
    diagnosis_has_evidence = await has_diagnosis_evidence(db, user.id)

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
    # 이번 학기 수강 과목은 성적 상한과 무관하게 전부 싣는다 — 상담이 이번 학기 목표와
    # 주제를 과목에 연결하는 근거라서, 잘리면 "그 과목은 안 듣는다"고 오해할 수 있다.
    current_courses: list[AcademicPerformance] = []
    if user.current_grade is not None and user.current_semester is not None:
        current_courses = list(
            await db.scalars(
                select(AcademicPerformance)
                .where(
                    AcademicPerformance.user_id == user.id,
                    AcademicPerformance.grade == user.current_grade,
                    AcademicPerformance.semester == user.current_semester,
                )
                .order_by(AcademicPerformance.created_at.asc())
            )
        )
    # 시간표에만 넣은 과목도 이번 학기 수강 과목이다 — 수강 과목 화면과 시간표 중 어느
    # 쪽으로 등록했든 상담이 같은 목록을 보게 합친다(과목명이 같으면 한 번만).
    current_course_entries: list[dict[str, Any]] = [
        _course_entry(c.subject, c.category, c.subject_code) for c in current_courses
    ]
    if user.current_grade is not None and user.current_semester is not None:
        timetables = list(
            await db.scalars(
                select(Timetable)
                .where(
                    Timetable.user_id == user.id,
                    Timetable.grade == user.current_grade,
                    Timetable.semester == user.current_semester,
                )
                .order_by(Timetable.is_default.desc(), Timetable.updated_at.desc())
            )
        )
        known = {entry["subject"].strip() for entry in current_course_entries}
        for timetable in timetables[:1]:
            for slot in timetable.slots or []:
                name = str(slot.get("course_name") or "").strip()
                if not name or name in known:
                    continue
                known.add(name)
                current_course_entries.append(
                    _course_entry(name, slot.get("group") or "기타", slot.get("subject_code"))
                )
    # 상한에 걸릴 때 어떤 행이 남는지가 정렬에 달려 있다. ORDER BY가 없으면 DB가
    # 임의로 고른 30건이 실려, 같은 질문에 매번 다른 근거를 드는 챗봇이 된다.
    # 다른 영역과 마찬가지로 최신 것부터 남긴다.
    awards = list(
        await db.scalars(
            select(Award)
            .where(Award.user_id == user.id)
            .order_by(Award.date.desc().nullslast(), Award.created_at.desc())
            .limit(MAX_AWARDS)
        )
    )
    volunteer = list(
        await db.scalars(
            select(VolunteerRecord)
            .where(VolunteerRecord.user_id == user.id)
            .order_by(
                VolunteerRecord.grade.desc(),
                VolunteerRecord.date.desc().nullslast(),
            )
            .limit(MAX_VOLUNTEER)
        )
    )
    # 출결은 탭이 없다 — 챗봇이 참고하는 재료로만 존재하므로(사용자 결정), 여기가
    # 유일한 노출 경로다. 학년 순으로 읽어야 모델이 흐름을 볼 수 있다.
    attendance = list(
        await db.scalars(
            select(Attendance)
            .where(Attendance.user_id == user.id)
            .order_by(Attendance.grade.asc())
        )
    )
    # 시험·수행평가 일정 중 다가오는(또는 지금 진행 중인) 것만 싣는다. 과거 일정
    # 전부를 넣으면 컨텍스트만 잡아먹고, 챗봇에게 필요한 건 "곧 있을 평가를 앞두고
    # 무엇을 준비할지"다. 오늘 기준으로 아직 끝나지 않은 일정을 시작일 순으로 담고,
    # 너무 먼 미래(약 4개월 뒤)까지는 보지 않는다.
    today = datetime.now(UTC).date()
    horizon = today + timedelta(days=120)
    upcoming_events = list(
        await db.scalars(
            select(CalendarEvent)
            .where(
                CalendarEvent.user_id == user.id,
                CalendarEvent.end_date >= today,
                CalendarEvent.start_date <= horizon,
            )
            .order_by(CalendarEvent.start_date.asc())
            .limit(20)
        )
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
    diagnosis = None
    if diagnosis_has_evidence:
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
            "freshman_academic_year": user.freshman_academic_year,
            # 이 문맥은 모델의 상식에 맡기지 않는다. 예를 들어 9월의 2학기는
            # 학기 초이므로 아직 성적·수행 결과를 물을 수 없다는 사실을 서버가
            # 명시해 준다.
            "academic_timing": get_academic_timing(
                freshman_academic_year=user.freshman_academic_year,
                current_grade=user.current_grade,
                current_semester=user.current_semester,
            ),
        },
        # 학생이 직접 말해준 것들 — 챗봇이 '수정' 모드에서 갱신하는 장기 메모리.
        "memory": interests,
        # 활동·성적 등의 빈 배열을 모델이 '실제 활동이 전혀 없었다'고 오해하지
        # 않도록, 학생부 업로드·반영 상태를 별도 사실로 제공한다.
        "school_record_coverage": school_record_coverage,
        "diagnosis": (
            {
                "strengths": diagnosis.strengths,
                "weaknesses": diagnosis.weaknesses,
                "opportunities": diagnosis.opportunities,
                "threats": diagnosis.threats,
                "career_thread": diagnosis.career_thread,
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
        # 학생이 등록한 이번 학기 수강 과목(온보딩·상담 화면 + 기본 시간표). 비어 있으면
        # 아직 등록하지 않은 것이지 듣는 과목이 없다는 뜻이 아니다.
        "current_semester_courses": current_course_entries,
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
            {
                "grade": v.grade,
                "date": v.date.isoformat() if v.date else None,
                "place": v.place,
                "content": v.content,
                "hours": v.hours,
            }
            for v in volunteer
        ],
        "attendance": [
            {"grade": a.grade, "total_days": a.total_days, "absence": a.absence, "note": a.note}
            for a in attendance
        ],
        # 다가오는 시험·수행평가. 챗봇이 "곧 있을 평가를 앞두고 무엇을 준비할지"를
        # 학생의 실제 일정에 맞춰 말할 수 있게 한다(오늘 이후~약 4개월).
        "upcoming_calendar_events": [
            {
                "type": e.event_type,
                "title": e.title,
                "subject": e.subject,
                "start_date": e.start_date.isoformat(),
                "end_date": e.end_date.isoformat(),
                "memo": e.memo,
            }
            for e in upcoming_events
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


def prepare_context_for_chat(
    context: dict[str, Any],
) -> tuple[dict[str, Any], ChatReferenceCatalog]:
    """LLM에 안전하게 보낼 문맥과 호출 내부 참조표를 만든다.

    활동·계획의 UUID, 부모 UUID처럼 모델이 복사할 수 있는 식별자를 제거한다. 활동의
    부모 연결은 같은 호출의 숫자 index로 바꿔, 모델이 계보를 이해하면서도 DB 식별자는
    전혀 알 수 없게 한다.
    """
    safe = {**context}
    safe["activities"] = [dict(activity) for activity in context.get("activities", [])]
    safe["plans"] = [dict(plan) for plan in context.get("plans", [])]
    catalog = ChatReferenceCatalog()
    activity_index_by_id: dict[str, int] = {}

    for activity in safe["activities"]:
        raw_id = activity.pop("id", None)
        if raw_id is None:
            continue
        index = catalog.register("activity", uuid.UUID(str(raw_id)))
        activity_index_by_id[str(raw_id)] = index
        activity["index"] = index

    for activity in safe["activities"]:
        parent_id = activity.pop("parent_activity_id", None)
        if parent_id is not None and str(parent_id) in activity_index_by_id:
            activity["parent_activity_index"] = activity_index_by_id[str(parent_id)]

    for plan in safe["plans"]:
        raw_id = plan.pop("id", None)
        if raw_id is None:
            continue
        plan["index"] = catalog.register("plan", uuid.UUID(str(raw_id)))

    return safe, catalog
