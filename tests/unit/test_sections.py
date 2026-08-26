from app.services.parser.sections import split_sections

SAMPLE = """1. 인적사항
성명: 홍길동
3. 출결상황
[1학년] 수업일수: 190 결석일수: 1
10. 행동특성 및 종합의견
성실하고 책임감이 강함.
"""


def test_split_sections_extracts_named_sections() -> None:
    sections = split_sections(SAMPLE)

    assert "인적사항" in sections
    assert "성명: 홍길동" in sections["인적사항"]

    assert "출결상황" in sections
    assert "[1학년] 수업일수: 190 결석일수: 1" in sections["출결상황"]

    assert "행동특성 및 종합의견" in sections
    assert "성실하고 책임감이 강함." in sections["행동특성 및 종합의견"]


def test_split_sections_returns_empty_dict_for_unrecognized_text() -> None:
    assert split_sections("아무 헤더도 없는 텍스트") == {}
