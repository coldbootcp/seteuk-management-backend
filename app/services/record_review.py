"""생기부 교체 업로드의 대조 — 이 생기부를 그대로 반영해도 되는가.

설정 탭에서 생기부를 올리거나 최신 것으로 바꾸면(mode=replace), 반영하기 전에 두 가지를
본다.

1. 이상(anomaly): 이 생기부가 학생의 지금 상황과 맞는가. 이름·입학 연도가 계정과 다르거나,
   아직 오지 않은 학기 기록이 있거나, 지난 학기가 통째로 빠진 옛 문서면 이상이다.
   전부 코드로 판정한다 — 챗봇은 이 결과를 근거로 학생에게 해명을 요청할 뿐이다.
2. 충돌(conflict): 학생이 서비스에서 직접 입력한 기록(source_upload_id가 빈 행)과 생기부가
   같은 것을 가리키는데 내용이 다른가. 같으면 생기부 쪽을 넣지 않고(중복), 다르면 학생에게
   하나씩 확인받는다. 학생이 빈칸으로 등록해 둔 이번 학기 수강 과목(성적 없는 행)은 충돌이
   아니라 생기부 성적으로 채울 자리다.

이상도 충돌도 없으면 서버가 바로 반영한다. 순번은 반영 단계(seteuk_service.import_result)와
같은 기준 — 현재 학기 이후를 거른 결과 — 으로 매긴다. 기준이 다르면 엉뚱한 항목이 들어간다.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import LLMUnavailableError
from app.models.academic_performance import AcademicPerformance
from app.models.activity import Activity
from app.models.attendance import Attendance
from app.models.user import User
from app.models.volunteer_record import VolunteerRecord
from app.schemas.seteuk import (
    RecordAnomaly,
    RecordConflict,
    RecordReview,
    SeteukAnalysisResult,
)
from app.services.llm import call_structured
from app.services.subject_catalog import normalize as normalize_subject

logger = logging.getLogger(__name__)

SECTIONS = (
    "attendance",
    "academic_performance",
    "volunteer_records",
    "activities",
)
_DESCRIPTION_LIMIT = 300


def _period_index(grade: int, semester: int | None) -> int:
    # 학기가 없는 학년 단위 기록은 그 학년의 끝(2학기)으로 본다 — "그 학년까지 채워져 있다".
    return (grade - 1) * 2 + ((semester or 2) - 1)


def _label(grade: int, semester: int | None) -> str:
    return f"{grade}학년 {semester}학기" if semester else f"{grade}학년"


def _compact(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


# ── 이상 ────────────────────────────────────────────────────────────────


def detect_anomalies(
    user: User,
    result: SeteukAnalysisResult,
    filtered: SeteukAnalysisResult,
    *,
    expected_period: tuple[int, int] | None,
) -> list[RecordAnomaly]:
    """이 생기부가 학생의 지금 상황과 맞지 않아 보이는 점.

    `result`는 거르기 전 원본, `filtered`는 현재 학기 이후를 거른 것이다. 둘의 차이가 곧
    "아직 오지 않은 학기의 기록"이다. `expected_period`는 입학 연도와 오늘 날짜로 계산한
    "지금쯤이어야 할 학기"로, 학생이 선언한 현재 학기가 낡았을 때의 기준이 된다.
    """
    anomalies: list[RecordAnomaly] = []

    if result.name_matches_account is False:
        anomalies.append(
            RecordAnomaly(
                kind="name_mismatch",
                message="생기부의 성명이 계정 이름과 다릅니다.",
            )
        )

    if (
        result.freshman_academic_year is not None
        and user.freshman_academic_year is not None
        and result.freshman_academic_year != user.freshman_academic_year
    ):
        anomalies.append(
            RecordAnomaly(
                kind="freshman_year_mismatch",
                message=(
                    f"생기부의 입학 학년도는 {result.freshman_academic_year}학년도인데 계정에는"
                    f" {user.freshman_academic_year}학년도로 되어 있습니다."
                ),
            )
        )

    dropped = sum(len(getattr(result, name)) - len(getattr(filtered, name)) for name in SECTIONS)
    latest = _latest_period(result)
    if dropped and user.current_grade is not None:
        anomalies.append(
            RecordAnomaly(
                kind="future_period",
                message=(
                    f"현재 학기({_label(user.current_grade, user.current_semester)})보다 뒤 시점의"
                    f" 기록이 {dropped}건 있습니다"
                    + (f"(가장 늦은 기록: {_label(*latest)})" if latest else "")
                    + "."
                ),
            )
        )
    elif latest and expected_period and _period_index(*latest) > _period_index(*expected_period):
        # 선언한 현재 학기는 넘지 않지만, 입학 연도로 계산한 학기를 넘는다 — 입학 연도나
        # 현재 학기 중 하나가 틀렸거나 다른 사람의 생기부다.
        anomalies.append(
            RecordAnomaly(
                kind="future_period",
                message=(
                    f"생기부에 {_label(*latest)} 기록이 있는데, 입학 학년도 기준으로는 아직"
                    f" {_label(*expected_period)}입니다."
                ),
            )
        )

    current = (
        (user.current_grade, user.current_semester or 1) if user.current_grade else expected_period
    )
    if latest and current and _period_index(*latest) < _period_index(*current) - 1:
        # 바로 앞 학기까지는 있어야 정상이다. 그보다 더 옛날에서 끝나면 지난 학기가 통째로 빠진
        # 옛 생기부일 가능성이 높다.
        anomalies.append(
            RecordAnomaly(
                kind="stale_record",
                message=(
                    f"생기부가 {_label(*latest)}에서 끝나는데 지금은 {_label(*current)}입니다."
                    " 그 사이 학기 기록이 없습니다."
                ),
            )
        )
    return anomalies


def _latest_period(result: SeteukAnalysisResult) -> tuple[int, int | None] | None:
    periods = (
        [(i.grade, i.semester) for i in result.academic_performance]
        + [(i.grade, i.semester) for i in result.activities]
        + [(i.grade, None) for i in result.attendance]
        + [(i.grade, None) for i in result.volunteer_records]
    )
    if not periods:
        return None
    return max(periods, key=lambda period: _period_index(*period))


# ── 충돌·중복 ───────────────────────────────────────────────────────────


class _ActivityMatch(BaseModel):
    existing_index: int
    record_index: int
    relation: Literal["same", "different"]
    difference: str = ""


class _ActivityMatchList(BaseModel):
    matches: list[_ActivityMatch] = []


_ACTIVITY_MATCH_PROMPT = """너는 고등학생의 활동 기록 두 목록을 대조하는 검토자다.
<학생_입력>은 학생이 서비스에 직접 적은 활동이고, <생기부>는 학교생활기록부에서 읽은 활동이다.
학생 입력의 각 활동이 생기부의 어느 활동과 **같은 실제 활동**을 가리키는지 찾아라.

- 같은 활동: 같은 과목·같은 주제로 같은 일을 했다는 기록. 표현이 달라도 같은 일이면 같다.
- 같은 활동이지만 사실이 다르면 relation="different"로 하고, 무엇이 다른지 difference에
  한 문장으로 적어라(예: "학생 입력은 설문 30명, 생기부는 50명").
- 같은 활동이고 사실이 어긋나지 않으면 relation="same".
- 대응하는 생기부 활동이 없으면 목록에 넣지 마라. 억지로 짝을 짓지 마라.
- 각 항목은 한 번만 짝지을 수 있다.
- 번호는 목록에 적힌 index만 써라.

JSON으로만 답하라: {"matches": [{"existing_index": 0, "record_index": 3,
"relation": "same", "difference": ""}]}"""


def _grade_values(row: AcademicPerformance) -> tuple[str | None, float | None, str | None]:
    return (
        _compact(row.achievement_grade) or None,
        row.raw_score,
        _compact(row.rank) or None,
    )


def _values_agree(existing: tuple, parsed: tuple) -> bool:
    # 한쪽이 비어 있는 칸은 비교하지 않는다 — 학생이 성취도만 적었을 수 있다.
    return all(a is None or b is None or a == b for a, b in zip(existing, parsed, strict=True))


def _grade_text(values: tuple) -> str:
    achievement, raw_score, rank = values
    parts = []
    if achievement:
        parts.append(f"성취도 {achievement}")
    if raw_score is not None:
        parts.append(f"원점수 {raw_score:g}")
    if rank:
        parts.append(f"석차등급 {rank}")
    return ", ".join(parts) or "성적 없음"


async def _manual_rows(db: AsyncSession, user_id, model) -> list:
    return list(
        await db.scalars(
            select(model).where(model.user_id == user_id, model.source_upload_id.is_(None))
        )
    )


async def compare_with_student_records(
    db: AsyncSession, user: User, filtered: SeteukAnalysisResult
) -> tuple[RecordReview, list[RecordAnomaly]]:
    """학생이 직접 입력한 기록과 대조해 반영 계획·중복·충돌을 만든다.

    반환하는 이상 목록은 대조 자체가 불완전했다는 신호다(활동 대조 LLM 실패 등).
    """
    plan: dict[str, list[int]] = {name: [] for name in SECTIONS}
    skipped: dict[str, int] = {}
    conflicts: list[RecordConflict] = []
    fill: dict[str, int] = {}
    extra_anomalies: list[RecordAnomaly] = []

    def skip(section: str) -> None:
        skipped[section] = skipped.get(section, 0) + 1

    # 성적 — 같은 학기·같은 과목끼리 숫자로 비교한다.
    manual_grades = await _manual_rows(db, user.id, AcademicPerformance)
    by_key: dict[tuple, AcademicPerformance] = {}
    for row in manual_grades:
        by_key.setdefault((row.grade, row.semester, normalize_subject(row.subject)), row)
    for index, item in enumerate(filtered.academic_performance):
        existing = by_key.get((item.grade, item.semester, normalize_subject(item.subject)))
        if existing is None:
            plan["academic_performance"].append(index)
            continue
        existing_values = _grade_values(existing)
        parsed_values = (
            _compact(item.achievement_grade) or None,
            item.raw_score,
            _compact(item.rank) or None,
        )
        if all(value is None for value in existing_values):
            # 학생이 수강 과목으로만 등록해 둔 빈칸 — 생기부 성적으로 채운다(과목 코드 유지).
            fill[str(existing.id)] = index
        elif _values_agree(existing_values, parsed_values):
            skip("academic_performance")
        else:
            conflicts.append(
                RecordConflict(
                    id=f"academic_performance:{index}",
                    section="academic_performance",
                    parsed_index=index,
                    existing_id=existing.id,
                    grade=item.grade,
                    semester=item.semester,
                    title=item.subject,
                    record_summary=_grade_text(parsed_values),
                    existing_summary=_grade_text(existing_values),
                    differences=[
                        f"{label}: 학생 입력 {mine}, 생기부 {theirs}"
                        for label, mine, theirs in zip(
                            ("성취도", "원점수", "석차등급"),
                            existing_values,
                            parsed_values,
                            strict=True,
                        )
                        if mine is not None and theirs is not None and mine != theirs
                    ],
                )
            )

    # 출결·봉사 — 같은 것이 이미 있으면 넣지 않는다(내용 비교까지는 하지 않는다).
    attendance_grades = {row.grade for row in await _manual_rows(db, user.id, Attendance)}
    for index, item in enumerate(filtered.attendance):
        if item.grade in attendance_grades:
            skip("attendance")
        else:
            plan["attendance"].append(index)

    volunteer = {
        (row.grade, row.date, row.hours)
        for row in await _manual_rows(db, user.id, VolunteerRecord)
    }
    for index, item in enumerate(filtered.volunteer_records):
        if item.date is not None and (item.grade, item.date, item.hours) in volunteer:
            skip("volunteer_records")
        else:
            plan["volunteer_records"].append(index)

    # 활동 — "같은 활동인가"는 문자열로 가를 수 없어 LLM이 짝을 짓고, 코드가 검증한다.
    manual_activities = await _manual_rows(db, user.id, Activity)
    matched_record: dict[int, tuple[_ActivityMatch, Activity]] = {}
    if manual_activities and filtered.activities:
        try:
            matched_record = await _match_activities(manual_activities, filtered)
        except LLMUnavailableError:
            logger.warning("activity matching failed for user %s", user.id)
            extra_anomalies.append(
                RecordAnomaly(
                    kind="activity_match_unavailable",
                    message=(
                        "직접 입력한 활동과 생기부 활동을 대조하지 못했습니다. 그대로 반영하면"
                        " 같은 활동이 두 번 들어갈 수 있습니다."
                    ),
                )
            )
    for index, item in enumerate(filtered.activities):
        match = matched_record.get(index)
        if match is None:
            plan["activities"].append(index)
            continue
        found, existing = match
        if found.relation == "same":
            skip("activities")
            continue
        conflicts.append(
            RecordConflict(
                id=f"activities:{index}",
                section="activities",
                parsed_index=index,
                existing_id=existing.id,
                grade=item.grade,
                semester=item.semester,
                title=existing.activity_name,
                record_summary=f"{item.activity_name} — {item.description[:_DESCRIPTION_LIMIT]}",
                existing_summary=(
                    f"{existing.activity_name} — {existing.description[:_DESCRIPTION_LIMIT]}"
                ),
                differences=[found.difference] if found.difference else [],
            )
        )

    review = RecordReview(
        state="needs_review" if conflicts else "clean_imported",
        conflicts=conflicts,
        import_plan=plan,
        fill_placeholders=fill,
        skipped_duplicates=skipped,
    )
    return review, extra_anomalies


async def _match_activities(
    manual: list[Activity], filtered: SeteukAnalysisResult
) -> dict[int, tuple[_ActivityMatch, Activity]]:
    """생기부 활동 순번 → (짝, 학생 활동). 학생 활동이 있는 학년의 생기부 활동만 대조한다."""
    grades = {row.grade for row in manual}
    candidates = [
        (index, item) for index, item in enumerate(filtered.activities) if item.grade in grades
    ]
    if not candidates:
        return {}

    def describe(grade: int, semester: int | None, category, subject, name, description) -> dict:
        return {
            "period": _label(grade, semester),
            "category": str(category),
            "subject": subject,
            "name": name,
            "description": (description or "")[:_DESCRIPTION_LIMIT],
        }

    payload = {
        "학생_입력": [
            {"index": i, **describe(r.grade, r.semester, r.activity_category, r.subject,
                                    r.activity_name, r.description)}
            for i, r in enumerate(manual)
        ],
        "생기부": [
            {"index": i, **describe(item.grade, item.semester, item.activity_category.value,
                                    item.subject, item.activity_name, item.description)}
            for i, (_, item) in enumerate(candidates)
        ],
    }
    response = await call_structured(
        _ACTIVITY_MATCH_PROMPT, json.dumps(payload, ensure_ascii=False), _ActivityMatchList
    )

    # 모델이 지어낸 번호·중복 짝은 버린다.
    result: dict[int, tuple[_ActivityMatch, Activity]] = {}
    used_existing: set[int] = set()
    for match in response.matches:
        if not (0 <= match.existing_index < len(manual)):
            continue
        if not (0 <= match.record_index < len(candidates)):
            continue
        if match.existing_index in used_existing:
            continue
        record_index = candidates[match.record_index][0]
        if record_index in result:
            continue
        used_existing.add(match.existing_index)
        result[record_index] = (match, manual[match.existing_index])
    return result


# ── 반영 ────────────────────────────────────────────────────────────────


def fill_placeholder_rows(
    rows: dict[str, AcademicPerformance], filtered: SeteukAnalysisResult, fill: dict[str, int]
) -> int:
    """학생이 빈칸으로 등록한 수강 과목 행에 생기부 성적을 채운다. 행은 학생 것으로 남긴다
    (과목 코드를 잃지 않게) — 다음 교체 때는 같은 성적이라 중복으로 건너뛴다."""
    filled = 0
    for row_id, index in fill.items():
        row = rows.get(row_id)
        if row is None or not (0 <= index < len(filtered.academic_performance)):
            continue
        item = filtered.academic_performance[index]
        row.units = item.units if item.units is not None else row.units
        row.achievement_grade = item.achievement_grade
        row.student_count = item.student_count
        row.raw_score = item.raw_score
        row.subject_average = item.subject_average
        row.std_deviation = item.std_deviation
        row.rank = item.rank
        filled += 1
    return filled

