from datetime import date

from app.services.academic_year import grade_for, infer_freshman_year, period_for, semester_of
from app.services.parser.enrollment import parse_freshman_academic_year


def test_enrollment_year_is_read_from_the_record() -> None:
    """학적사항은 입학 시점을 그대로 밝힌다 — 추론할 필요가 없다."""
    section = (
        "2018년 2월 8일  흥덕중학교  제3학년 졸업\n"
        "2018년 3월 5일  가온고등학교  제1학년 입학\n"
        "2021년 1월 8일  가온고등학교  제3학년 졸업\n"
    )
    assert parse_freshman_academic_year(section) == 2018


def test_missing_enrollment_gives_no_anchor() -> None:
    """입학 기록이 없으면 기준점도 없다. 지어내지 않는다."""
    assert parse_freshman_academic_year("2021년 1월 8일  가온고등학교  제3학년 졸업\n") is None


def test_january_enrolment_belongs_to_the_previous_academic_year() -> None:
    """학년도는 3월에 시작한다. 1~2월은 앞 학년도다."""
    assert parse_freshman_academic_year("2019년 1월 3일  가온고  제1학년 입학") == 2018


def test_dates_map_to_grades_through_the_anchor() -> None:
    assert grade_for(date(2019, 1, 11), 2018) == 1  # 1학년 2학기 끝자락
    assert grade_for(date(2019, 6, 19), 2018) == 2
    assert grade_for(date(2020, 8, 13), 2018) == 3
    # 3년 밖은 판정하지 않는다 — 졸업 후 기록이거나 잘못 읽은 날짜다.
    assert grade_for(date(2022, 5, 1), 2018) is None
    assert grade_for(date(2019, 6, 19), None) is None


def test_semester_comes_from_the_month_alone() -> None:
    assert semester_of(date(2019, 6, 19)) == 1
    assert semester_of(date(2020, 8, 31)) == 1
    assert semester_of(date(2019, 12, 4)) == 2
    assert semester_of(date(2020, 1, 8)) == 2


def test_period_needs_both() -> None:
    assert period_for(date(2019, 12, 4), 2018) == (2, 2)
    assert period_for(date(2019, 12, 4), None) is None


def test_anchor_can_still_be_inferred_from_dated_grade_evidence() -> None:
    """학적사항이 없는 문서도 있을 수 있다. 봉사처럼 날짜와 학년을 함께 가진
    기록이 있으면 거기서 기준점을 되짚을 수 있다."""
    assert infer_freshman_year([(date(2019, 6, 19), 2), (date(2020, 8, 13), 3)]) == 2018
    assert infer_freshman_year([]) is None
