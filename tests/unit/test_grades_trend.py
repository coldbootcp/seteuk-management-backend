from app.services.diagnosis.data import _parse_rank


def test_plain_rank_strings_parse() -> None:
    assert _parse_rank("1") == 1
    assert _parse_rank("9") == 9
    assert _parse_rank(" 3 ") == 3


def test_rank_with_a_denominator_takes_the_grade() -> None:
    """생기부에 "3/280"처럼 수강자 수가 붙어 오는 표기가 있다."""
    assert _parse_rank("3/280") == 3


def test_values_that_are_not_a_grade_are_dropped() -> None:
    """석차등급은 1~9다. 그 밖의 값이 rank 칼럼에 들어와도 평균을 오염시키면 안 된다."""
    assert _parse_rank(None) is None
    assert _parse_rank("") is None
    assert _parse_rank("A") is None  # 성취도가 잘못 들어온 경우
    assert _parse_rank("0") is None
    assert _parse_rank("10") is None
    assert _parse_rank("P") is None  # 이수(pass) 과목
