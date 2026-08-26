from app.services.parser.blocks import slice_grade_semester_blocks, slice_subject_blocks

SETEUK_SAMPLE = """
[2학년]
1학기
수학Ⅰ: 지수함수 모델링 탐구를 수행함. 학급 발표를 진행함.
한국사(1학기): 근현대사 프로젝트를 진행함.
"""

CHANGCHE_SAMPLE = """
[2학년]
1학기
동아리 부장으로 프로젝트를 진행함.
2학기
체육대회 응원단장으로 참가함.
"""


def test_slice_subject_blocks_splits_on_whitelisted_subjects() -> None:
    blocks = slice_subject_blocks(SETEUK_SAMPLE, ["수학Ⅰ", "한국사"])

    assert len(blocks) == 2
    assert blocks[0].subject == "수학Ⅰ"
    assert blocks[0].grade == 2
    assert blocks[0].semester == 1
    assert "지수함수 모델링" in blocks[0].text

    assert blocks[1].subject == "한국사"
    assert "근현대사 프로젝트" in blocks[1].text


def test_slice_subject_blocks_ignores_non_whitelisted_names() -> None:
    blocks = slice_subject_blocks(SETEUK_SAMPLE, ["영어"])

    assert blocks == []


def test_slice_subject_blocks_returns_empty_for_no_subjects() -> None:
    assert slice_subject_blocks(SETEUK_SAMPLE, []) == []


def test_slice_grade_semester_blocks_splits_by_headers() -> None:
    blocks = slice_grade_semester_blocks(CHANGCHE_SAMPLE)

    assert len(blocks) == 2
    assert blocks[0].grade == 2
    assert blocks[0].semester == 1
    assert "동아리 부장" in blocks[0].text
    assert blocks[1].semester == 2
    assert "체육대회" in blocks[1].text


def test_slice_grade_semester_blocks_without_headers_returns_empty() -> None:
    assert slice_grade_semester_blocks("헤더 없는 자유 서술 텍스트") == []
