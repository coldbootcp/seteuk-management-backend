from app.services.parser.anchors import semester_markers
from app.services.parser.blocks import slice_grade_semester_blocks


def _found(text: str) -> list[str]:
    return [m.group(0) for m in semester_markers(text)]


def test_grade_table_header_is_not_a_semester_marker() -> None:
    """성적표 머리글은 "교과 / 과목 / 1학기 / 2학기 / 비고"로 두 학기가 붙어 나온다.
    이걸 구분 표시로 읽으면 뒤따르는 세특이 전부 2학기로 쓸려 들어간다 — 실제
    생기부에서 1학년 세특 32건이 모두 2학기가 되고 1학기가 텅 비었다."""
    header = "[1학년]\n교과\n과목\n1학기\n2학기\n비고\n단위\n수\n국어\n"
    assert _found(header) == []


def test_semester_mentioned_inside_a_sentence_is_not_a_marker() -> None:
    """"1학기의 후속 연구로"처럼 본문에 나오는 표현도 구분 표시가 아니다."""
    prose = "영어Ⅱ: 개론서를 탐독하며 습득한 1학기의 후속 연구로 드론 활용을 탐구함.\n"
    assert _found(prose) == []


def test_a_standalone_label_is_still_a_marker() -> None:
    """제 줄에 홀로 서 있고 짝이 붙어 있지 않으면 진짜 구분 표시다 — 학기를 나누는
    다른 학교 양식을 막지 않아야 한다."""
    text = "[2학년]\n1학기\n자율활동: 학급 회장으로 활동함.\n" + "본문 " * 20 + "\n2학기\n진로활동: 캠프 참가.\n"
    assert _found(text) == ["1학기", "2학기"]

    blocks = slice_grade_semester_blocks(text)
    assert [(b.grade, b.semester) for b in blocks] == [(2, 1), (2, 2)]


def test_a_grade_block_without_real_markers_stays_year_level() -> None:
    """구분 표시가 없으면 학기를 지어내지 않고 학년 단위로 남긴다. 자율활동·진로활동은
    원래 학기가 없는 기록이라 이게 사실에 맞다."""
    text = "[1학년]\n교과\n과목\n1학기\n2학기\n비고\n자율활동: 학급 행사를 준비함.\n"
    blocks = slice_grade_semester_blocks(text)
    assert [(b.grade, b.semester) for b in blocks] == [(1, None)]
