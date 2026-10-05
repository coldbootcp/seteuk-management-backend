
from app.services.parser.tables import parse_volunteer_records

# 실제 생기부는 제목 행("학 년 | 봉 사 활 동 실 적")이 먼저 오고 머리글이 둘째
# 행에 온다. 봉사 파서는 그 제목으로 자기 표를 알아본다.
VOLUNTEER_TABLE = [
    ["학 년", "봉 사 활 동 실 적", "", "", ""],
    ["", "일자", "장소", "내용", "시간"],
    ["2", "2023.07.15", "지역아동센터", "학습 멘토링", "8"],
]


def test_parse_volunteer_records_extracts_hours_as_int() -> None:
    items = parse_volunteer_records([VOLUNTEER_TABLE])

    assert len(items) == 1
    assert items[0].grade == 2
    assert items[0].hours == 8
    assert items[0].place == "지역아동센터"


def test_parse_functions_skip_tables_without_matching_headers() -> None:
    unrelated_table = [["과목", "단위수"], ["수학", "4"]]

    assert parse_volunteer_records([unrelated_table]) == []


def test_parse_volunteer_records_collapses_line_wrap_to_a_space() -> None:
    # pdfplumber preserves the PDF's own column-width word wrap as a literal "\n" —
    # a layout artifact, not a real line break. It's collapsed to a single space
    # rather than removed outright, since there's no reliable way to tell a mid-word
    # wrap ("종\n료" -> "종료") apart from a wrap between two separate words.
    table = [
        ["학 년", "봉 사 활 동 실 적", "", "", ""],
        ["", "일자", "장소", "내용", "시간"],
        ["1", "2023.05.17.", "가온고등학교", "교내 스포츠 어울마당 종\n료 후 교내 환경정리", "1"],
    ]

    items = parse_volunteer_records([table])

    assert "\n" not in items[0].content
    assert items[0].content == "교내 스포츠 어울마당 종 료 후 교내 환경정리"


def test_parse_volunteer_records_handles_split_title_and_header_rows() -> None:
    # Real exports put a merged title in row 0 ("학년 | 봉사활동실적") and the actual
    # column labels — with an unlabeled leftmost 학년 column — in row 1.
    table = [
        ["학 년", "봉 사 활 동 실 적", None, None, None],
        [None, "일자 또는 기간", "장소 또는 주관기관명", "활동내용", "시간"],
        ["1", "2018.08.29.", "지역아동센터", "학습지도", "1"],
        [None, "2018.09.22.", "수원YMCA", "환경캠페인", "8"],
    ]

    items = parse_volunteer_records([table])

    assert len(items) == 2
    assert items[0].grade == 1
    assert items[0].hours == 1
    assert items[1].grade == 1
    assert items[1].place == "수원YMCA"


def test_volunteer_semester_comes_from_the_date() -> None:
    """봉사활동실적 표는 학년만 열로 갖지만 일자가 있다. 학기까지 정할 수 있으면
    흐름 맵이 그 학기에만 놓을 수 있다 — 비어 있으면 학년 단위로 두 학기에
    함께 보여야 한다."""
    table = [
        ["학 년", "봉 사 활 동 실 적", "", "", "", ""],
        ["", "일자 또는 기간", "장소 또는 주관기관명", "활동내용", "시간", "누계시간"],
        ["1", "2018.03.23.", "(학교)가온고등학교", "봉사활동 사전교육", "1", "1"],
        ["", "2018.11.05.", "(개인)문기지역아동센터", "학습지도", "2", "3"],
    ]
    items = parse_volunteer_records([table])

    assert [(i.grade, i.semester) for i in items] == [(1, 1), (1, 2)]
    assert [i.hours for i in items] == [1, 2]


def test_only_the_volunteer_table_is_read() -> None:
    """"내용"이라는 낱말만으로 표를 고르면 세특처럼 본문에 그 말이 우연히 들어간
    표까지 걸린다. 실제 생기부에서 세특 표 하나가 봉사 파서에 잡혔다."""
    seteuk = [
        ["과목", "세 부 능 력 및 특 기 사 항"],
        ["1", "한국사: 답사 보고서의 내용을 일자별로 정리하고 3시간에 걸쳐 발표함"],
    ]
    assert parse_volunteer_records([seteuk]) == []
