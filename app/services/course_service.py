"""이번 학기 수강 과목 — 온보딩과 상담 화면에서 학생이 고른 과목을 성적 테이블에 둔다.

새 테이블을 만들지 않고 `academic_performance`에 성적 칸이 빈 행으로 넣는다. 로드맵
마디의 수강 과목(`roadmap_service.list_node_courses`)과 상담 챗봇의 컨텍스트가 이미 이
테이블을 "그 학기에 듣는 과목"으로 읽고 있어서, 여기 넣으면 별도 연결 없이 그대로
이어진다. 학기가 끝나 성적을 입력하면 같은 행이 성적 행이 된다.

이 화면에서 바꾸는 것은 "이 화면이 만든 행"뿐이다 — 생기부에서 파싱된 행이나 이미
성적이 들어간 행은 학생의 기록이므로 목록에 보여 주되 지우지 않는다(locked).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ProfileIncompleteError
from app.models.academic_performance import AcademicPerformance
from app.models.user import User
from app.schemas.subject import (
    CurrentCourseInput,
    CurrentCourseRead,
    CurrentCoursesResponse,
)
from app.services.subject_catalog import curriculum_for_student, get_subject

CUSTOM_CATEGORY = "기타"
# 파서(parser/grades.py)가 쓰는 교과 이름과 맞춘다 — 같은 테이블에서 섞여 읽힌다.
_GROUP_TO_CATEGORY = {"한국사": "사회", "기술·가정/정보": "기술·가정"}


def _category_for(group: str) -> str:
    return _GROUP_TO_CATEGORY.get(group, group)


def _is_editable(row: AcademicPerformance) -> bool:
    """이 화면이 지우고 다시 쓸 수 있는 행 — 직접 입력했고 성적이 하나도 없는 행."""
    return row.source_upload_id is None and not any(
        value is not None
        for value in (
            row.achievement_grade,
            row.raw_score,
            row.rank,
            row.subject_average,
            row.std_deviation,
            row.student_count,
        )
    )


def _current_period(user: User) -> tuple[int, int]:
    if user.current_grade is None or user.current_semester is None:
        raise ProfileIncompleteError("프로필(학년-학기)을 먼저 설정해주세요")
    return user.current_grade, user.current_semester


async def _rows_for_period(
    db: AsyncSession, user: User, grade: int, semester: int
) -> list[AcademicPerformance]:
    rows = await db.scalars(
        select(AcademicPerformance)
        .where(
            AcademicPerformance.user_id == user.id,
            AcademicPerformance.grade == grade,
            AcademicPerformance.semester == semester,
        )
        .order_by(AcademicPerformance.created_at.asc())
    )
    return list(rows)


def _to_read(row: AcademicPerformance) -> CurrentCourseRead:
    return CurrentCourseRead(
        id=row.id,
        subject=row.subject,
        subject_code=row.subject_code,
        category=row.category,
        units=row.units,
        is_custom=row.subject_code is None,
        locked=not _is_editable(row),
    )


async def get_current_courses(db: AsyncSession, user: User) -> CurrentCoursesResponse:
    grade, semester = _current_period(user)
    rows = await _rows_for_period(db, user, grade, semester)
    return CurrentCoursesResponse(
        grade=grade,
        semester=semester,
        curriculum=curriculum_for_student(user.freshman_academic_year, user.current_grade),
        courses=[_to_read(row) for row in rows],
    )


async def set_current_courses(
    db: AsyncSession, user: User, courses: list[CurrentCourseInput]
) -> CurrentCoursesResponse:
    """학생이 고른 목록으로 이번 학기 수강 과목을 맞춘다(덮어쓰기)."""
    grade, semester = _current_period(user)
    rows = await _rows_for_period(db, user, grade, semester)

    for row in rows:
        if _is_editable(row):
            await db.delete(row)
    kept = [row for row in rows if not _is_editable(row)]
    kept_codes = {row.subject_code for row in kept if row.subject_code}
    kept_names = {row.subject.strip() for row in kept}

    seen: set[str] = set()
    for course in courses:
        subject = get_subject(course.subject_code) if course.subject_code else None
        name = subject.name if subject else (course.custom_name or "").strip()
        key = subject.code if subject else f"custom:{name}"
        if not name or key in seen:
            continue
        seen.add(key)
        # 생기부·성적으로 이미 있는 과목은 다시 만들지 않는다.
        if (subject and subject.code in kept_codes) or name in kept_names:
            continue
        db.add(
            AcademicPerformance(
                user_id=user.id,
                grade=grade,
                semester=semester,
                category=_category_for(subject.group) if subject else CUSTOM_CATEGORY,
                subject=name,
                subject_code=subject.code if subject else None,
                units=subject.default_units if subject else None,
            )
        )
    await db.commit()
    return await get_current_courses(db, user)
