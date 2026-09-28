from datetime import date

from app.services import subject_catalog as catalog


def _names(query: str, curriculum: str, limit: int = 8) -> list[str]:
    return [s.name for s in catalog.search(query, curriculum, limit)]


def test_codes_are_unique_and_resolvable() -> None:
    codes = [s.code for s in catalog.SUBJECTS]
    assert len(codes) == len(set(codes))
    assert catalog.get_subject("2022:대수").name == "대수"
    assert catalog.get_subject("2022:수학Ⅰ") is None  # 2015 과목은 2022 코드로 없다
    assert catalog.get_subject("없는 코드") is None


def test_short_prefix_lists_common_subjects_first() -> None:
    """"수"를 치면 공통수학부터 — 흔히 듣는 과목이 앞에 온다."""
    assert _names("수", "2022")[:2] == ["공통수학1", "공통수학2"]
    assert _names("수", "2015")[:3] == ["수학", "수학Ⅰ", "수학Ⅱ"]


def test_student_shorthand_finds_the_subject() -> None:
    assert _names("수1", "2015") == ["수학Ⅰ"]
    # 2022 개정의 대수는 옛 수학Ⅰ 자리라 "수1"로도 찾는다.
    assert _names("수1", "2022") == ["대수"]
    assert _names("물1", "2015") == ["물리학Ⅰ"]
    assert "확률과 통계" in _names("확통", "2022")
    assert _names("기가", "2022") == ["기술·가정"]


def test_search_ignores_spacing_and_roman_numerals() -> None:
    assert "영어 독해와 작문" in _names("영어독해", "2022")
    assert _names("수학 1", "2015")[0] == "수학Ⅰ"
    assert _names("ㅁㅁ", "2022") == []
    assert catalog.search("", "2022") == []


def test_curriculum_follows_the_entry_year() -> None:
    assert catalog.curriculum_for_student(2025, None) == "2022"
    assert catalog.curriculum_for_student(2024, None) == "2015"
    # 입학 연도를 모르면 지금 학년에서 거꾸로 센다(2026년 2학년 = 2025 입학).
    assert catalog.curriculum_for_student(None, 2, date(2026, 9, 27)) == "2022"
    assert catalog.curriculum_for_student(None, 3, date(2026, 9, 27)) == "2015"


def test_common_examples_exist_for_every_semester() -> None:
    for curriculum in ("2015", "2022"):
        for grade in (1, 2, 3):
            for semester in (1, 2):
                examples = catalog.common_for_period(curriculum, grade, semester)
                assert examples, (curriculum, grade, semester)
                assert all(s.curriculum == curriculum for s in examples)
    assert catalog.common_for_period("2022", 1, 2)[0].name == "공통국어2"
