"""생기부의 개인정보를 가린다.

원본 PDF는 업로드 요청 안에서만 메모리에 있고, 디스크(DB)에 남는 것과 외부 LLM에
나가는 것은 이 모듈을 거친 것뿐이다. 두 경로를 나눠 둔다.

- `redact_pdf`: PDF에서 글자와 이미지를 **실제로 지운다**(PyMuPDF redaction). 위에 검은
  칠만 얹는 것과 달라서, 텍스트 레이어나 이미지 데이터가 파일에서 없어진다.
- `sanitize_text`: LLM에 보내는 세특·창체 텍스트에서 학생 이름과 식별 패턴을 바꾼다.

한계: 교사·친구 이름은 문서가 "이름"이라고 표시하지 않아 찾을 수 없다. 학생 본인
성명과 형식이 분명한 패턴(주민번호·전화번호·이메일·학교명·주소 줄)만 지운다.
"""

import re

import pymupdf

from app.services.parser.extract import extract_tables, extract_text
from app.services.parser.identity import parse_student_name, parse_teacher_names
from app.services.parser.sections import split_sections

_RRN = re.compile(r"\d{6}\s*[-‐–]\s*[\d*●○Xx]{7}")
_PHONE = re.compile(r"0\d{1,2}\s*[-.)]\s*\d{3,4}\s*[-.]\s*\d{4}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_SCHOOL = re.compile(r"[가-힣]{2,20}(?:고등학교|중학교|초등학교|여고|여중)")
# "주소 : ..." 라벨이 붙은 줄은 값을 줄 끝까지 주소로 본다.
_ADDRESS_LINE = re.compile(r"주\s*소\s*[:：]?\s*(\S.*)")

_BLACK = (0, 0, 0)


def _spaced_variants(name: str) -> set[str]:
    """정렬 때문에 글자 사이가 벌어진 표기("홍 길 동")까지 같이 찾는다."""
    return {name, " ".join(name), "  ".join(name)}


def _identity_terms(text: str, name: str | None) -> set[str]:
    terms: set[str] = set()
    for pattern in (_RRN, _PHONE, _EMAIL, _SCHOOL):
        terms.update(m.group(0) for m in pattern.finditer(text))
    if name:
        terms.update(_spaced_variants(name))
    return terms


def _address_terms(personal_section: str) -> set[str]:
    return {m.group(1).strip() for m in _ADDRESS_LINE.finditer(personal_section)}


def redact_pdf(pdf_bytes: bytes) -> tuple[bytes, str | None]:
    """개인정보를 지운 PDF와, 대조에만 쓸 학생 성명(없으면 None)을 돌려준다.

    지우지 못하면 예외를 그대로 올린다 — 호출부는 원본을 저장하지 않고 실패로 처리해야
    한다(가리기에 실패한 파일을 "일단 저장"하면 이 모듈의 의미가 없다).
    """
    text = extract_text(pdf_bytes)
    sections = split_sections(text)
    personal = sections.get("인적사항", "")
    name = parse_student_name(personal)
    terms = _identity_terms(text, name) | _address_terms(personal)
    # 담임 이름은 표지 표에만 있다 — 첫 쪽들만 본다.
    terms.update(parse_teacher_names(extract_tables(pdf_bytes, max_pages=2)))
    terms.discard("")

    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            page_text = page.get_text()
            for term in terms:
                if term not in page_text:
                    continue
                for rect in page.search_for(term):
                    page.add_redact_annot(rect, fill=_BLACK)
            _redact_personal_photo(page)
            _redact_issuer_header(page)
            page.apply_redactions(
                images=pymupdf.PDF_REDACT_IMAGE_REMOVE,
                graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
            )
        return doc.tobytes(garbage=4, deflate=True, clean=True), name


# 정부24 등에서 발급한 출력본은 매 페이지 위쪽에 "문서확인번호 … (신청인 : 성명)" 띠를
# 글자가 아니라 벡터 도형(글리프 윤곽)으로 찍는다. 텍스트 검색으로는 찾을 수 없으니
# 본문이 시작하기 전의 위쪽 띠를 통째로 지운다. 본문에는 이 높이에 아무것도 없다.
_HEADER_BAND_HEIGHT = 45


def _redact_issuer_header(page: pymupdf.Page) -> None:
    band = pymupdf.Rect(0, 0, page.rect.width, _HEADER_BAND_HEIGHT)
    if page.get_text("words", clip=band):
        return  # 이 높이에 실제 글자가 있는 문서는 본문을 지우지 않도록 건드리지 않는다.
    page.add_redact_annot(band, fill=(1, 1, 1))


def _redact_personal_photo(page: pymupdf.Page) -> None:
    """인적사항이 있는 쪽의 증명사진을 지운다.

    사진은 인적사항 제목 위(표지 영역)에 놓이기도 해서 위치로 가르지 않고 모양으로 본다:
    세로로 긴 작은 이미지. 학적사항 쪽 도장 같은 정사각형 이미지는 건드리지 않는다.
    """
    # 제목이 "인 적 사 항"처럼 글자 사이가 벌어져 있어 공백을 없애고 본다.
    if not re.search(r"인적(?:[·ㆍ・･.]?학적)?사항", re.sub(r"\s+", "", page.get_text())):
        return
    page_area = page.rect.width * page.rect.height
    for info in page.get_image_info():
        rect = pymupdf.Rect(info["bbox"])
        if rect.height > rect.width * 1.1 and rect.width * rect.height < page_area / 8:
            page.add_redact_annot(rect, fill=_BLACK)


def sanitize_text(
    text: str, student_name: str | None, teacher_names: list[str] | None = None
) -> str:
    """LLM에 보낼 텍스트에서 학생·담임 이름과 식별 패턴을 바꾼다."""
    text = _RRN.sub("", text)
    text = _PHONE.sub("", text)
    text = _EMAIL.sub("", text)
    text = _SCHOOL.sub("OO학교", text)
    for teacher in teacher_names or []:
        text = text.replace(teacher, "선생님")
    if student_name:
        for variant in sorted(_spaced_variants(student_name), key=len, reverse=True):
            text = text.replace(variant, "학생")
        # 세특 본문은 성을 빼고 이름만 부르는 일이 흔하다("길동이는").
        given = student_name[1:]
        if len(given) >= 2:
            text = text.replace(given, "학생")
    return text
