from datetime import date

from app.services.parser.dates import normalize_date


def test_normalize_date_handles_dot_separated_format() -> None:
    assert normalize_date("2023.05.20") == date(2023, 5, 20)


def test_normalize_date_handles_korean_format() -> None:
    assert normalize_date("2023년 5월 20일") == date(2023, 5, 20)


def test_normalize_date_handles_hyphen_format() -> None:
    assert normalize_date("2023-05-20") == date(2023, 5, 20)


def test_normalize_date_returns_none_for_empty_or_invalid() -> None:
    assert normalize_date(None) is None
    assert normalize_date("") is None
    assert normalize_date("모름") is None
