from datetime import date

from app.services.academic_timing import get_academic_timing


def test_second_semester_in_september_is_current_early() -> None:
    timing = get_academic_timing(
        freshman_academic_year=2025,
        current_grade=2,
        current_semester=2,
        reference_date=date(2026, 9, 8),
    )

    assert timing["status"] == "current_early"
    assert "2학년 2학기 학기 초" in timing["summary"]
    assert "성적·수행평가·세특·활동 결과" in timing["summary"]


def test_other_grade_is_not_treated_as_current_semester() -> None:
    timing = get_academic_timing(
        freshman_academic_year=2025,
        current_grade=1,
        current_semester=2,
        reference_date=date(2026, 9, 8),
    )

    assert timing["status"] == "past"
    assert "과거 기록" in timing["summary"]
