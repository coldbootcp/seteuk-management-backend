from app.services import subject_contents
from app.services.chat.context import _course_entry
from app.services.subject_catalog import SUBJECTS, get_subject


def test_every_content_entry_is_a_real_catalog_subject_with_units():
    # 로더가 카탈로그에 없는 코드·중복 코드를 만나면 ValueError를 낸다.
    for code in subject_contents.covered_codes():
        content = subject_contents.get_content(code)
        assert get_subject(code) is not None
        assert content is not None
        assert content.summary
        assert content.units and all(content.units)


def test_unknown_or_missing_code_has_no_content():
    assert subject_contents.get_content(None) is None
    assert subject_contents.get_content("2022:없는과목") is None


def test_course_entry_marks_curriculum_and_attaches_content_when_known():
    entry = _course_entry("대수", "수학", "2022:대수")
    assert entry["from_catalog"] is True
    assert entry["curriculum"] == "2022 개정"
    assert entry["course_type"] == "일반선택"
    content = subject_contents.get_content("2022:대수")
    if content is None:
        assert "content" not in entry
    else:
        assert entry["content"]["units"] == list(content.units)


def test_custom_school_course_has_no_curriculum_or_content():
    entry = _course_entry("우리학교 자율과목", "기타", None)
    assert entry == {"subject": "우리학교 자율과목", "category": "기타", "from_catalog": False}


def test_every_2022_general_course_and_three_specialized_tracks_are_covered():
    # 경남교육 2024-008 자료는 2022 보통 교과 전체와 과학·체육·예술 계열 선택 과목을 다룬다.
    expected = {
        s.code
        for s in SUBJECTS
        if s.curriculum == "2022"
        and (s.track is None or s.track in {"과학 계열", "체육 계열", "예술 계열"})
    }
    assert expected - subject_contents.covered_codes() == set()


def test_units_keep_area_names_from_the_official_table():
    content = subject_contents.get_content("2022:역학과 에너지")
    assert content is not None
    areas = [u.split(":")[0] for u in content.units]
    assert areas == ["시공간과 운동", "열과 에너지", "탄성파와 소리"]
