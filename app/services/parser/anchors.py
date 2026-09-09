import re

GRADE_HEADER_PATTERN = re.compile(r"\[(\d)학년\]")
SEMESTER_LABEL_PATTERN = re.compile(r"(\d)학기")

# 성적표 머리글은 "교과 / 과목 / 1학기 / 2학기 / 비고"처럼 두 학기가 바로 붙어 나온다.
# 이 둘을 구분 표시로 읽으면 뒤따르는 세특이 전부 뒤쪽 학기(2학기)로 쓸려 들어간다.
_ADJACENT_LABEL_GAP = 8


def semester_markers(text: str) -> list[re.Match]:
    """진짜 학기 구분 표시만 고른다.

    "N학기"라는 글자는 문서 곳곳에 나온다 — 성적표의 열 머리글이기도 하고
    ("…습득한 1학기의 후속 연구로…")처럼 본문 속 표현이기도 하다. 실제 생기부에서
    이 둘을 구분 표시로 오인하는 바람에 1학년 세특 32건이 전부 2학기로 들어가고
    1학기가 텅 비는 일이 있었다.

    구분 표시는 제 줄에 홀로 서 있고, 짝이 되는 학기 라벨이 바로 옆에 붙어 있지
    않다. 그 두 조건을 모두 만족하는 것만 남긴다 — 판단이 서지 않으면 학기를
    비워 두는 편이 낫다. 학년 단위 기록으로 남을 뿐 사라지지는 않는다.
    """
    matches = list(SEMESTER_LABEL_PATTERN.finditer(text))
    kept: list[re.Match] = []
    for i, match in enumerate(matches):
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        line_end = len(text) if line_end == -1 else line_end
        if text[line_start : match.start()].strip() or text[match.end() : line_end].strip():
            continue  # 줄 안에 다른 글자가 있다 — 본문이거나 표 셀이다.
        neighbours = [
            other
            for j, other in enumerate(matches)
            if j != i and abs(other.start() - match.start()) <= _ADJACENT_LABEL_GAP
        ]
        if neighbours:
            continue  # 1학기/2학기가 붙어 있다 — 표의 열 머리글이다.
        kept.append(match)
    return kept


def nearest_preceding(anchors: list[re.Match], position: int) -> re.Match | None:
    """Return the anchor match with the greatest start offset that is still <= position."""
    candidate = None
    for anchor in anchors:
        if anchor.start() > position:
            break
        candidate = anchor
    return candidate
