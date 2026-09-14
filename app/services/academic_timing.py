"""학생이 말한 학년·학기를 실제 학사 시점과 함께 해석한다.

학기 정보만으로는 "2학기"가 이미 끝난 기록인지, 막 시작한 현재 학기인지 알 수 없다.
상담 모델이 현재 학기 성적이나 수행 결과를 이미 나온 사실처럼 묻지 않도록, 서버가
기준일과 입학 연도를 함께 계산해 명시적인 문맥으로 만든다.
"""

from datetime import date
from typing import Literal, TypedDict

TimingStatus = Literal["current_early", "current_mid", "current_late", "past", "future", "unknown"]


class AcademicTiming(TypedDict):
    reference_date: str
    status: TimingStatus
    summary: str


def _semester_phase(semester: int, month: int) -> Literal["early", "mid", "late"] | None:
    """일반적인 국내 고교 학사 흐름의 대략적 위치만 제공한다.

    학교별 시험·수행평가 일정은 다르므로 정확한 평가일을 지어내지 않는다. 3~7월은
    1학기, 8~12월은 2학기라는 넓은 구간 안에서만 학기 초·중·말을 구분한다.
    """
    if semester == 1 and month in (3, 4):
        return "early"
    if semester == 1 and month == 5:
        return "mid"
    if semester == 1 and month in (6, 7):
        return "late"
    if semester == 2 and month in (8, 9):
        return "early"
    if semester == 2 and month == 10:
        return "mid"
    if semester == 2 and month in (11, 12):
        return "late"
    return None


def get_academic_timing(
    *,
    freshman_academic_year: int | None,
    current_grade: int | None,
    current_semester: int | None,
    reference_date: date | None = None,
) -> AcademicTiming:
    """현재 날짜 기준으로 학생이 선언한 학기의 시간적 상태를 돌려준다."""
    today = reference_date or date.today()
    common = {"reference_date": today.isoformat()}

    if (
        not freshman_academic_year
        or current_grade not in (1, 2, 3)
        or current_semester not in (1, 2)
    ):
        return {
            **common,
            "status": "unknown",
            "summary": (
                "현재 학년·학기 또는 입학 연도가 확정되지 않아 학사 시점을 판단할 수 "
                "없습니다. 완료된 성적·활동을 추측하지 마세요."
            ),
        }

    expected_grade = today.year - freshman_academic_year + 1
    if expected_grade > 3 or current_grade < expected_grade:
        return {
            **common,
            "status": "past",
            "summary": (
                f"{today.isoformat()} 기준으로 {current_grade}학년 {current_semester}학기는 "
                "과거 기록입니다. 실제로 저장된 기록만 근거로 다루세요."
            ),
        }
    if expected_grade < 1 or current_grade > expected_grade:
        return {
            **common,
            "status": "future",
            "summary": (
                f"{today.isoformat()} 기준으로 {current_grade}학년 {current_semester}학기는 "
                "아직 오지 않은 시점입니다. 완료된 성적·활동이 있다고 가정하지 마세요."
            ),
        }

    phase = _semester_phase(current_semester, today.month)
    if phase is not None:
        korean_phase = {"early": "학기 초", "mid": "학기 중", "late": "학기 말"}[phase]
        return {
            **common,
            "status": f"current_{phase}",
            "summary": (
                f"{today.isoformat()} 기준 현재는 {current_grade}학년 "
                f"{current_semester}학기 {korean_phase}입니다. "
                "이 학기의 성적·수행평가·세특·활동 결과는 아직 확정된 정보가 아니므로 "
                "묻거나 추측하지 마세요. "
                "학생이 직접 말한 계획·관심·제약과 이미 저장된 과거 기록만 근거로 삼으세요."
            ),
        }

    return {
        **common,
        "status": "unknown",
        "summary": (
            f"{today.isoformat()}은 정규 학기 중으로 단정하기 어려운 기간입니다. "
            f"{current_grade}학년 {current_semester}학기의 완료 여부를 추측하지 마세요."
        ),
    }
