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


def test_short_subject_name_does_not_get_merged_into_the_previous_subject() -> None:
    """예전에는 "다음 성적 조각까지 15자 미만이면 같은 과목의 2학기"로 판단했다.
    다음 과목명이 짧으면(예: "문학" 2글자 + 교과 "국어" 2글자) 그 문턱을 넘지
    못해 서로 다른 두 과목이 하나로 합쳐졌다 — 실제 생기부에서 "독서" 다음의
    "문학"이 이렇게 통째로 사라지고 그 값이 "독서"의 2학기 성적으로 잘못 붙었다.
    두 과목 사이에 과목명 글자가 조금이라도 있으면 다른 과목으로 봐야 한다."""
    text = (
        "[2학년] 교과 과목 국어 독서 5 94/63.5(27.1) A(217) 2 "
        "국어 문학 5 88/60.8(26.7) A(220) 1 "
    )
    items = parse_academic_performance_from_text(text)
    by_subject = {item.subject: item for item in items}

    assert set(by_subject) == {"독서", "문학"}
    assert len([i for i in items if i.subject == "독서"]) == 1
    assert by_subject["독서"].raw_score == 94.0
    assert by_subject["문학"].raw_score == 88.0


def test_pass_fail_subject_does_not_swallow_the_next_subjects_name() -> None:
    """P(합격/불합격) 과목은 석차 칸 자체가 없다. 석차를 항상 필수로 요구하면
    정규식이 바로 다음 과목의 단위수 숫자를 이 과목의 석차로 잘못 삼킨다 —
    실제 생기부에서 "보건" 다음의 "공학 일반"이 이름째로 사라지고
    "P 기술·가정/제2외국어/한문/교양 공학 일반"이라는 가짜 과목명이 생겼다."""
    text = (
        "[2학년] 교과 과목 기술·가정 보건 1 P P "
        "기술·가정 공학 일반 3 98/96.1(6.8) A(7) · "
    )
    items = parse_academic_performance_from_text(text)
    by_subject = {item.subject: item for item in items}

    assert set(by_subject) == {"보건", "공학 일반"}
    assert by_subject["보건"].achievement_grade == "P"
    assert by_subject["보건"].rank is None
    assert by_subject["보건"].raw_score is None
    assert by_subject["공학 일반"].achievement_grade == "A"
    assert by_subject["공학 일반"].units == 3
    assert by_subject["공학 일반"].raw_score == 98.0


def test_two_pass_fail_subjects_in_both_semesters_stay_separate() -> None:
    """P 과목이 두 학기 모두 있으면(석차 칸 없이 단위수-P-P가 두 번 반복) 서로
    붙어 있는 두 학기를 하나로 묶어야 하고, 그 뒤에 오는 다른 과목과는 섞이지
    않아야 한다."""
    text = (
        "[2학년] 교과 과목 기술·가정 민주시민(고) 1 P P 1 P P "
        "기술·가정 로봇 요소 2 95/93.3(3.1) A(7) · 2 92/92.4(2.1) A(10) · "
    )
    items = parse_academic_performance_from_text(text)
    civics = [i for i in items if i.subject == "민주시민(고)"]
    robotics = [i for i in items if i.subject == "로봇 요소"]

    assert [i.semester for i in civics] == [1, 2]
    assert all(i.achievement_grade == "P" for i in civics)
    assert [i.semester for i in robotics] == [1, 2]
    assert robotics[0].raw_score == 95.0 and robotics[1].raw_score == 92.0
