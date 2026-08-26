from app.services.parser.grades import (
    extract_subject_names_from_text,
    infer_category,
    parse_academic_performance,
    parse_academic_performance_from_text,
)

SAMPLE = """
[2학년]
1학기
수학Ⅰ 4 96/78.4(12.1) A(236) 1
국어 3 88/75.0(10.0) B(230)
2학기
수학Ⅰ 4 90/70.0(11.0) A(236)
"""

# Linear text as PyMuPDF actually renders a real 교과학습발달상황 table: subject name,
# then a same-line-adjacent "단위수 원점수/평균(표준편차) 성취도(인원) 석차등급" tuple,
# with the 1학기/2학기 tuples for one subject running back-to-back.
REAL_SHAPE_TEXT = (
    "[1학년] 교과 과목 국어 4 97/65.2(26.1) A(236) 1 4 94/64.2(26.5) A(227) 3 "
    "미술 3 P P · "
)


def test_parse_academic_performance_maps_grade_and_semester() -> None:
    items = parse_academic_performance(SAMPLE)

    assert len(items) == 3
    first = items[0]
    assert first.grade == 2
    assert first.semester == 1
    assert first.subject == "수학Ⅰ"
    assert first.category == "수학"
    assert first.units == 4
    assert first.raw_score == 96
    assert first.subject_average == 78.4
    assert first.std_deviation == 12.1
    assert first.achievement_grade == "A"
    assert first.student_count == 236
    assert first.rank == "1"


def test_parse_academic_performance_splits_grade_and_count_separately() -> None:
    items = parse_academic_performance(SAMPLE)
    second = items[1]

    assert second.achievement_grade == "B"
    assert second.student_count == 230
    assert second.rank is None


def test_parse_academic_performance_anchors_semester_by_label() -> None:
    items = parse_academic_performance(SAMPLE)
    third = items[2]

    assert third.grade == 2
    assert third.semester == 2
    assert third.subject == "수학Ⅰ"


def test_infer_category_falls_back_to_subject_name() -> None:
    assert infer_category("수학Ⅰ") == "수학"
    assert infer_category("한국사") == "사회"
    assert infer_category("중국어Ⅰ") == "제2외국어"
    assert infer_category("특이과목명") == "특이과목명"


def test_parse_academic_performance_from_text_pairs_semesters() -> None:
    items = parse_academic_performance_from_text(REAL_SHAPE_TEXT)

    korean = [item for item in items if item.subject == "국어"]
    assert len(korean) == 2
    assert korean[0].semester == 1
    assert korean[0].units == 4
    assert korean[0].raw_score == 97.0
    assert korean[0].subject_average == 65.2
    assert korean[0].std_deviation == 26.1
    assert korean[0].achievement_grade == "A"
    assert korean[0].student_count == 236
    assert korean[0].rank == "1"
    assert korean[1].semester == 2
    assert korean[1].rank == "3"


def test_parse_academic_performance_from_text_handles_pass_fail_subjects() -> None:
    items = parse_academic_performance_from_text(REAL_SHAPE_TEXT)
    art = next(item for item in items if item.subject == "미술")

    assert art.achievement_grade == "P"
    assert art.raw_score is None
    assert art.student_count is None
    assert art.rank is None


def test_extract_subject_names_from_text_dedupes() -> None:
    subjects = extract_subject_names_from_text(REAL_SHAPE_TEXT)

    assert subjects == ["국어", "미술"]
