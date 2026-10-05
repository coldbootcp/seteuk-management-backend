"""학기가 행으로 놓이는 서식의 성적 표를 셀 좌표로 읽는 파서."""

import pymupdf

from app.services.parser.grades import parse_academic_performance_from_layout

_COLS = [20, 60, 110, 190, 220, 320, 400, 470, 560]
_HEADER = ["학기", "교과", "과목", "단위수", "원점수/과목평균", "성취도", "석차등급", "비고"]


def _grade_table_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    rows = [(100, 120), (120, 140), (140, 190), (190, 240)]  # 제목, 머리글, 1학기, 2학기
    for top, bottom in rows:
        for left, right in zip(_COLS, _COLS[1:], strict=False):
            page.draw_rect(pymupdf.Rect(left, top, right, bottom), width=0.5)

    def write(col: int, y: float, text: str) -> None:
        page.insert_text((_COLS[col] + 2, y), text, fontname="korea", fontsize=7)

    write(0, 113, "[3학년]")
    for i, label in enumerate(_HEADER):
        write(i, 133, label)

    def semester_row(top: float, semester: str, subjects: list[tuple]) -> None:
        write(0, top + 25, semester)
        for k, (category, name_lines, units, score, achievement, rank) in enumerate(subjects):
            y = top + 12 + k * 20
            write(1, y, category)
            for j, line in enumerate(name_lines):  # 과목명이 접히면 기준줄 위아래에 놓인다
                write(2, y - 3 * (len(name_lines) - 1) + j * 6, line)
            write(3, y, units)
            write(4, y, score)
            write(5, y, achievement)
            write(6, y, rank)

    semester_row(
        140,
        "1",
        [
            ("국어", ["독서"], "4", "59/63.9(19.3)", "E(262)", "6"),
            ("영어", ["심화 영어 독해", "Ⅰ"], "4", "26/47.5(20.0)", "C(263)", "5"),
        ],
    )
    semester_row(190, "2", [("수학", ["미적분"], "3", "58/58.1(19.2)", "E(150)", "5")])
    return doc.tobytes()


def test_semester_rows_keep_their_own_semester() -> None:
    items = parse_academic_performance_from_layout(_grade_table_pdf())
    by_semester = {
        (i.grade, i.semester): [x.subject for x in items if x.semester == i.semester] for i in items
    }
    assert set(by_semester) == {(3, 1), (3, 2)}
    assert by_semester[(3, 2)] == ["미적분"]


def test_wrapped_subject_names_are_restored_and_values_align() -> None:
    items = parse_academic_performance_from_layout(_grade_table_pdf())
    english = next(i for i in items if i.subject == "심화 영어 독해Ⅰ")
    assert (english.semester, english.units, english.raw_score) == (1, 4, 26.0)
    assert (english.achievement_grade, english.student_count, english.rank) == ("C", 263, "5")
    assert english.std_deviation == 20.0
