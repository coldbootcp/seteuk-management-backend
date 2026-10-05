import pymupdf

from app.services.parser.extract import extract_text
from app.services.parser.redact import redact_pdf, sanitize_text


def _sample_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    font = "korea"  # 내장 CJK 한글 폰트
    lines = [
        "1. 인적사항",
        "성명 : 홍길동  성별 : 남",
        "주민등록번호 : 020510-1234567",
        "주소 : 경기도 용인시 기흥구 1005동",
        "2. 학적사항",
        "2018년 3월 5일 가온고등학교 제1학년 입학",
        "3. 출결상황",
    ]
    for i, line in enumerate(lines):
        page.insert_text((50, 100 + i * 20), line, fontname=font, fontsize=11)
    return doc.tobytes()


def test_redact_removes_identifying_text_and_returns_name() -> None:
    redacted, name = redact_pdf(_sample_pdf())
    text = extract_text(redacted)
    assert name == "홍길동"
    assert "홍길동" not in text
    assert "1234567" not in text
    assert "1005동" not in text
    assert "가온고등학교" not in text
    # 개인정보가 아닌 본문은 남는다.
    assert "학적사항" in text
    assert "입학" in text


def test_sanitize_replaces_name_given_name_and_patterns() -> None:
    text = "홍길동은 가온고등학교에서 탐구했다. 길동이는 hong@example.com, 010-1234-5678로 연락."
    out = sanitize_text(text, "홍길동")
    assert "홍길동" not in out and "길동" not in out
    assert "가온고등학교" not in out
    assert "hong@example.com" not in out
    assert "010-1234-5678" not in out
    assert "학생" in out


def test_sanitize_without_name_still_strips_patterns() -> None:
    out = sanitize_text("주민번호 020510-1234567", None)
    assert "1234567" not in out


def _combined_header_pdf() -> bytes:
    """새 서식: 인적사항과 학적사항이 "1. 인적·학적사항" 한 구역이다."""
    doc = pymupdf.open()
    page = doc.new_page()
    lines = [
        "1. 인적·학적사항",
        "성명 : 강민재  성별 : 남",
        "주소 : 경기도 수원시 영통구 4001호",
        "2022년 3월 2일 광교고등학교 제1학년 입학",
        "2. 출결상황",
    ]
    for i, line in enumerate(lines):
        page.insert_text((50, 100 + i * 20), line, fontname="korea", fontsize=11)
    return doc.tobytes()


def test_combined_personal_section_is_split_for_both_parsers() -> None:
    from app.services.parser.enrollment import parse_freshman_academic_year
    from app.services.parser.identity import parse_student_name
    from app.services.parser.sections import split_sections

    sections = split_sections(extract_text(_combined_header_pdf()))
    assert parse_student_name(sections["인적사항"]) == "강민재"
    assert parse_freshman_academic_year(sections["학적사항"]) == 2022


def test_redact_handles_combined_personal_section() -> None:
    redacted, name = redact_pdf(_combined_header_pdf())
    text = extract_text(redacted)
    assert name == "강민재"
    assert "강민재" not in text
    assert "4001호" not in text
    assert "광교고등학교" not in text
