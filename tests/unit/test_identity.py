from app.services.parser.identity import parse_student_name


def test_reads_a_plain_name() -> None:
    assert parse_student_name("성명: 홍길동") == "홍길동"


def test_reads_a_name_followed_by_other_fields() -> None:
    # 실제 생기부 인적사항은 성명 뒤에 성별·주민등록번호가 이어 붙는다.
    text = "성명 : 홍길동   성별 : 남   주민등록번호 : 000000-0000000"
    assert parse_student_name(text) == "홍길동"


def test_tolerates_spaced_label_and_missing_separator() -> None:
    assert parse_student_name("성 명  김세특") == "김세특"


def test_returns_none_when_no_name_present() -> None:
    assert parse_student_name("3. 출결상황\n[1학년] 수업일수: 190") is None


def test_returns_none_for_empty_text() -> None:
    assert parse_student_name("") is None
