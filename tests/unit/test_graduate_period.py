from datetime import date

from app.services.seteuk_service import _expected_period_from_freshman_year


def test_a_graduate_is_always_at_the_end_of_third_year() -> None:
    """졸업생은 오늘이 몇 월이든 3학년 2학기까지 확정된 생기부를 가진다. 예전에는 3~8월에
    3학년 1학기로 계산돼 졸업생의 3학년 2학기 기록이 반려됐다."""
    for today in (date(2026, 4, 10), date(2026, 9, 29), date(2027, 5, 1)):
        assert _expected_period_from_freshman_year(2022, today) == (3, 2)


def test_a_current_student_follows_the_calendar() -> None:
    assert _expected_period_from_freshman_year(2024, date(2026, 4, 10)) == (3, 1)
    assert _expected_period_from_freshman_year(2024, date(2026, 10, 1)) == (3, 2)
    assert _expected_period_from_freshman_year(2025, date(2026, 4, 10)) == (2, 1)
