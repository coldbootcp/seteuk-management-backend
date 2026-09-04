from datetime import date

from app.services.parser.tables import (
    parse_awards,
    parse_reading_activities,
    parse_volunteer_records,
)

AWARDS_TABLE = [
    ["대회명", "등급", "수상일자"],
    ["수학 경시대회", "금상(1위)", "2023.05.20"],
]

VOLUNTEER_TABLE = [
    ["학년", "일자", "장소", "내용", "시간"],
    ["2", "2023.07.15", "지역아동센터", "학습 멘토링", "8"],
]

READING_TABLE = [
    ["학년", "학기", "과목", "도서명", "저자"],
    ["2", "1", "생명과학", "이기적 유전자", "리처드 도킨스"],
]


def test_parse_awards_normalizes_date_and_keeps_raw() -> None:
    items = parse_awards([AWARDS_TABLE])

    assert len(items) == 1
    assert items[0].name == "수학 경시대회"
    assert items[0].rank == "금상(1위)"
    assert items[0].date == date(2023, 5, 20)
    assert items[0].raw_date == "2023.05.20"


def test_parse_volunteer_records_extracts_hours_as_int() -> None:
    items = parse_volunteer_records([VOLUNTEER_TABLE])

    assert len(items) == 1
    assert items[0].grade == 2
    assert items[0].hours == 8
    assert items[0].place == "지역아동센터"


def test_parse_reading_activities_reads_subject_and_semester() -> None:
    items = parse_reading_activities([READING_TABLE])

    assert len(items) == 1
    assert items[0].grade == 2
    assert items[0].semester == 1
    assert items[0].subject == "생명과학"
    assert items[0].title == "이기적 유전자"
    assert items[0].author == "리처드 도킨스"


def test_parse_functions_skip_tables_without_matching_headers() -> None:
    unrelated_table = [["과목", "단위수"], ["수학", "4"]]

    assert parse_awards([unrelated_table]) == []
    assert parse_volunteer_records([unrelated_table]) == []


def test_parse_awards_does_not_forward_fill_blank_rank() -> None:
    # A blank 등급 cell means "no rank awarded", not "same rank as the row above" —
    # forward-filling it (as the grouping columns elsewhere legitimately do) would be
    # wrong here. Also covers the "수상연월일" header wording used by real exports,
    # which doesn't contain "일자"/"날짜" as a substring.
    table = [
        ["수상명", "등급(위)", "수상연월일"],
        ["대회 A", "금상(1위)", "2023.05.20"],
        ["교과우수상", "", "2023.06.01"],
    ]

    items = parse_awards([table])

    assert items[0].rank == "금상(1위)"
    assert items[1].rank is None
    assert items[1].date == date(2023, 6, 1)


def test_parse_volunteer_records_collapses_line_wrap_to_a_space() -> None:
    # pdfplumber preserves the PDF's own column-width word wrap as a literal "\n" —
    # a layout artifact, not a real line break. It's collapsed to a single space
    # rather than removed outright, since there's no reliable way to tell a mid-word
    # wrap ("종\n료" -> "종료") apart from a wrap between two separate words.
    table = [
        ["학년", "일자", "장소", "내용", "시간"],
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


def test_parse_reading_activities_extracts_multiple_books_from_one_cell() -> None:
    # Real exports don't give each book its own row — one semester's cell holds a
    # "(N학기) 책제목(저자), 책제목(저자)" free-text list instead.
    table = [
        ["학 년", "과목 또는 영역", "독서활동 상황"],
        ["2", "국어", "(1학기) 아몬드(손원평), 인간실격(다자이 오사무)"],
    ]

    items = parse_reading_activities([table])

    assert len(items) == 2
    assert items[0].grade == 2
    assert items[0].semester == 1
    assert items[0].subject == "국어"
    assert items[0].title == "아몬드"
    assert items[0].author == "손원평"
    assert items[1].title == "인간실격"
    assert items[1].author == "다자이 오사무"


def test_award_grade_comes_from_participants_and_semester_from_the_date() -> None:
    """생기부 수상 표에는 학년 열이 없다. 참가대상이 학년을, 수상연월일이 학기를
    알려 주므로 둘을 합쳐 파싱 시점에 채운다."""
    table = [
        ["수상명", "등급(위)", "수상연월일", "수여기관", "참가대상(참가인원)"],
        ["과학 탐구 대회", "금상(1위)", "2020.08.13.", "가온고등학교장", "3학년(216명)"],
    ]
    [item] = parse_awards([table])
    assert (item.grade, item.semester) == (3, 1)
    assert item.participants == "3학년(216명)"


def test_ambiguous_participants_are_filled_from_the_same_document() -> None:
    """"수강자"나 "1·2학년 공동"처럼 학년을 못 읽는 행이 많다. 학년을 읽어낸 행이
    "이 학사연도가 몇 학년이었는지"를 알려 주므로, 그 대응으로 나머지를 채운다.
    바깥 시계(오늘 날짜)는 쓰지 않는다 — 생기부는 몇 해 전 문서일 수 있다."""
    table = [
        ["수상명", "등급(위)", "수상연월일", "수여기관", "참가대상(참가인원)"],
        ["NIE 역량강화대회", "동상(4위)", "2019.01.07.", "가온고", "1학년 7차일반(227명)"],
        ["교과우수상(영어)", "", "2019.01.11.", "가온고", "수강자"],
        ["모의재판 경연대회", "우수상(2위)", "2019.01.11.", "가온고", "1‧2학년 중 참가자(60명)"],
    ]
    items = parse_awards([table])
    # 2018 학년도가 1학년이라는 것을 첫 행에서 배웠고, 1월은 그 학년도의 2학기다.
    assert [(i.grade, i.semester) for i in items] == [(1, 2), (1, 2), (1, 2)]


def test_award_without_any_grade_signal_stays_empty() -> None:
    """근거가 없으면 비워 둔다. 날짜 하나로 학년을 지어내면, 미래 학기 필터가
    지어낸 값을 근거로 기록을 버리게 된다."""
    table = [
        ["수상명", "등급(위)", "수상연월일", "수여기관", "참가대상(참가인원)"],
        ["표창장", "", "2019.01.11.", "가온고", "전교생(929명)"],
    ]
    [item] = parse_awards([table])
    assert item.grade is None and item.semester is None
