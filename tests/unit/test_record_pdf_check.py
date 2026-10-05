"""생기부 파일 검사 — 받자마자 원인별로 안내한다(진짜 PDF로 검증)."""

import pymupdf
import pytest

from app.core.exceptions import UnsupportedFileError

# conftest가 통합 테스트용으로 seteuk_service._check_record_pdf를 얕은 검사로 바꿔 두므로,
# 모듈을 불러올 때의 진짜 함수를 붙잡아 쓴다.
from app.services.seteuk_service import _check_record_pdf as check_record_pdf

_SECTIONS = ["인적사항", "학적사항", "출결상황", "교과학습발달상황", "창의적체험활동상황"]


def _pdf(lines: list[str], **save_kwargs: object) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    y = 60
    for line in lines:
        page.insert_text((50, y), line, fontname="korea", fontsize=10)
        y += 14
    return doc.tobytes(**save_kwargs)


def _record_like() -> bytes:
    lines = []
    for number, title in enumerate(_SECTIONS, start=1):
        lines.append(f"{number}. {title}")
        lines.extend(["내용 " * 12] * 3)
    return _pdf(lines)


def _message(data: bytes) -> str:
    with pytest.raises(UnsupportedFileError) as caught:
        check_record_pdf(data)
    return str(caught.value)


def test_record_like_pdf_passes() -> None:
    check_record_pdf(_record_like())


def test_non_pdf_file_says_pdf_only() -> None:
    assert "PDF 파일만" in _message(b"\xff\xd8\xff\xe0 jpeg bytes")


def test_corrupt_pdf_says_cannot_open() -> None:
    assert "열 수 없습니다" in _message(b"%PDF-1.4\n" + b"x" * 500)


def test_encrypted_pdf_says_remove_password() -> None:
    data = _pdf(["보안 문서"], encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="1234")
    assert "암호" in _message(data)


def test_image_only_pdf_says_no_text() -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), False)
    pix.clear_with(200)
    page.insert_image(page.rect, pixmap=pix)
    assert "글자를 읽을 수 없습니다" in _message(doc.tobytes())


def test_unrelated_pdf_says_not_a_record() -> None:
    data = _pdf(["Weekly meeting notes " * 4] * 6)
    assert "생기부)로 보이지 않는" in _message(data)
