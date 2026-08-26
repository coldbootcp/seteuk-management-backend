from app.services.parser.attendance import parse_attendance, parse_attendance_from_tables

SAMPLE = """
[1학년]
수업일수: 190 결석일수: 1 특기사항: 질병 결석 1일
[2학년]
수업일수: 192 결석일수: 0
"""

# Shape observed in a real 생기부 export: 결석일수 spans three merged sub-columns
# (질병/미인정/기타) and the header can be split across a page break, so the table
# title row precedes the real header row.
REAL_SHAPE_TABLE = [
    ["3. 출 결 상 황", None, None, None, None, None, None],
    ["학년", "수업일수", "결석일수", None, None, "지각", "특기사항"],
    [None, None, "질병", "미인정", "기타", None, None],
    ["1", "190", ".", ".", ".", ".", "개근"],
    ["2", "177", "1", ".", ".", ".", "원격수업일수 68일"],
]


def test_parse_attendance_extracts_per_grade_blocks() -> None:
    items = parse_attendance(SAMPLE)

    assert len(items) == 2
    assert items[0].grade == 1
    assert items[0].total_days == 190
    assert items[0].absence == 1
    assert items[0].note == "질병 결석 1일"

    assert items[1].grade == 2
    assert items[1].total_days == 192
    assert items[1].absence == 0
    assert items[1].note is None


def test_parse_attendance_ignores_column_order_variants() -> None:
    text = "[3학년]\n결석일수: 2 수업일수: 191"

    items = parse_attendance(text)

    assert items[0].grade == 3
    assert items[0].total_days == 191
    assert items[0].absence == 2


def test_parse_attendance_returns_empty_without_grade_headers() -> None:
    assert parse_attendance("수업일수: 190 결석일수: 0") == []


def test_parse_attendance_from_tables_sums_absence_subcolumns() -> None:
    items = parse_attendance_from_tables([REAL_SHAPE_TABLE])

    assert len(items) == 2
    assert items[0].grade == 1
    assert items[0].total_days == 190
    assert items[0].absence == 0
    assert items[0].note == "개근"

    assert items[1].grade == 2
    assert items[1].total_days == 177
    assert items[1].absence == 1
    assert items[1].note == "원격수업일수 68일"


def test_parse_attendance_from_tables_ignores_unrelated_tables() -> None:
    unrelated = [["수상명", "등급"], ["대회", "금상"]]

    assert parse_attendance_from_tables([unrelated]) == []
