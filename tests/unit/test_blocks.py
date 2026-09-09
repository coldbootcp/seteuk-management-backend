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


def test_subject_whitespace_variance_between_grades_table_and_narrative() -> None:
    """같은 과목명이 문서 안에서도 다르게 적힌다 — 성적표 열은 PDF 줄바꿈에 걸려
    "로봇 소프트웨\\n어 개발"이 되지만(공백으로 남는다), 세특 본문에서는 줄바꿈 없이
    "로봇 소프트웨어 개발"로 그대로 나온다. 실제 생기부에서 이 차이 때문에 그 과목의
    세특 전체가 앵커를 못 찾아 조용히 사라졌었다.

    화이트리스트(정본)는 성적표 쪽 표기(공백 있음)를 쓰고, 본문은 공백 없는 표기를
    쓰는 상황을 재현한다.
    """
    text = "[1학년]\n로봇 소프트웨어 개발: 프로그래밍 기초를 학습함.\n"
    blocks = slice_subject_blocks(text, ["로봇 소프트웨 어 개발"])

    assert len(blocks) == 1
    # subject는 정본(화이트리스트) 표기로 남아야 한다 — 성적표의 같은 과목과
    # 문자열이 일치해야 "한 학기에만 개설된 과목" 추론 등에서 키가 어긋나지 않는다.
    assert blocks[0].subject == "로봇 소프트웨 어 개발"
    assert "프로그래밍 기초" in blocks[0].text


def test_short_subjects_are_not_made_more_permissive() -> None:
    """공백이 없는 짧은 과목명(예: "기하")은 예전과 똑같이 정확히 일치해야 한다 —
    유연한 매칭은 화이트리스트 표기 안에 있는 공백에만 적용된다."""
    blocks = slice_subject_blocks("[3학년]\n기하: 도형 문제를 풀이함.\n", ["기하"])
    assert len(blocks) == 1
    assert blocks[0].subject == "기하"


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
