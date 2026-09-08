"""전국 모집요강 원문을 찾고, 안전하게 자기소개서 표식을 추출한다.

바로요강은 원문을 재배포하지 않고 대입정보포털의 파일 URL을 연결하므로 '발견용'
목록으로만 쓴다. 실제 판정과 화면의 원문 링크는 반드시 그 대입정보포털 파일을
기준으로 한다. 추출 실패 또는 표식 부재는 전형 미요구 판정이 아니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import pymupdf

BARO_UNIVERSITIES_URL = "https://www.baroyogang.com/api/universities?type=university"
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
_WRITING_MARKER = re.compile(r"자기\s*소개서|자소서", re.IGNORECASE)


@dataclass(frozen=True)
class AdmissionGuide:
    university_code: str
    university_name: str
    admission_year: int
    title: str
    source_url: str


@dataclass(frozen=True)
class GuideInspection:
    guide: AdmissionGuide
    extracted_text: str
    marker_contexts: list[str]
    inspected_at: datetime


class WritingRequirementSourceError(RuntimeError):
    """원문 목록 또는 파일을 신뢰할 수 있게 읽지 못했을 때 사용한다."""


def _normalise_text(value: str) -> str:
    return "\n".join(line.strip() for line in value.replace("\r", "").splitlines() if line.strip())


def extract_pdf_text(content: bytes) -> str:
    """텍스트 PDF만 판독한다. 스캔본·HWP를 빈 문서로 오판하지 않도록 예외 처리한다."""
    try:
        with pymupdf.open(stream=content, filetype="pdf") as document:
            text = "\n".join(page.get_text("text") for page in document)
    except Exception as error:  # PyMuPDF raises several format-specific exception classes.
        raise WritingRequirementSourceError("PDF 원문을 판독하지 못했습니다.") from error
    text = _normalise_text(text)
    if len(text) < 100:
        raise WritingRequirementSourceError("텍스트를 읽을 수 없는 모집요강입니다.")
    return text


def marker_contexts(text: str, *, radius: int = 280) -> list[str]:
    """후속 규칙 검증에 사용할 짧은 근거 문맥만 반환한다."""
    contexts: list[str] = []
    for marker in _WRITING_MARKER.finditer(text):
        excerpt = " ".join(text[max(0, marker.start() - radius) : marker.end() + radius].split())
        if excerpt and excerpt not in contexts:
            contexts.append(excerpt)
    return contexts


class WritingRequirementSource:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(45.0, connect=15.0),
            follow_redirects=True,
            headers={"User-Agent": "SeteukLab writing-requirement verifier/1.0"},
        )

    async def __aenter__(self) -> WritingRequirementSource:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def find_susi_guide(
        self, *, university_code: str, admission_year: int
    ) -> AdmissionGuide | None:
        response = await self._client.get(BARO_UNIVERSITIES_URL)
        response.raise_for_status()
        try:
            universities = response.json()
        except ValueError as error:
            raise WritingRequirementSourceError("모집요강 목록 응답을 읽지 못했습니다.") from error
        row = next(
            (
                item
                for item in universities
                if str(item.get("univ_code")) == university_code
                and str(item.get("academic_year")) == str(admission_year)
            ),
            None,
        )
        if not row:
            return None
        brochures = row.get("brochures") or []
        selected = next(
            (
                brochure
                for brochure in brochures
                if "수시모집요강" in str(brochure.get("title", ""))
                and str(brochure.get("download_url", "")).startswith("https://www.adiga.kr/")
            ),
            None,
        )
        if not selected:
            return None
        return AdmissionGuide(
            university_code=university_code,
            university_name=str(row.get("univ_name", "")),
            admission_year=admission_year,
            title=str(selected.get("title", "수시모집요강")),
            source_url=str(selected["download_url"]),
        )

    async def fetch_susi_guides(self, *, admission_year: int) -> list[AdmissionGuide]:
        """해당 학년 4년제 대학의 공식 수시모집요강 링크만 수집한다."""
        response = await self._client.get(BARO_UNIVERSITIES_URL)
        response.raise_for_status()
        try:
            universities = response.json()
        except ValueError as error:
            raise WritingRequirementSourceError("모집요강 목록 응답을 읽지 못했습니다.") from error
        guides: list[AdmissionGuide] = []
        for row in universities:
            if str(row.get("academic_year")) != str(admission_year):
                continue
            selected = next(
                (
                    brochure
                    for brochure in (row.get("brochures") or [])
                    if "수시모집요강" in str(brochure.get("title", ""))
                    and str(brochure.get("download_url", "")).startswith("https://www.adiga.kr/")
                ),
                None,
            )
            if selected:
                guides.append(
                    AdmissionGuide(
                        university_code=str(row.get("univ_code", "")),
                        university_name=str(row.get("univ_name", "")),
                        admission_year=admission_year,
                        title=str(selected.get("title", "수시모집요강")),
                        source_url=str(selected["download_url"]),
                    )
                )
        return guides

    async def inspect_guide(self, guide: AdmissionGuide) -> GuideInspection:
        async with self._client.stream("GET", guide.source_url) as response:
            response.raise_for_status()
            declared_size = int(response.headers.get("content-length", "0") or 0)
            if declared_size > MAX_DOCUMENT_BYTES:
                raise WritingRequirementSourceError(
                    "모집요강 파일이 안전한 판독 크기를 초과합니다."
                )
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_DOCUMENT_BYTES:
                    raise WritingRequirementSourceError(
                        "모집요강 파일이 안전한 판독 크기를 초과합니다."
                    )
                chunks.append(chunk)
        content = b"".join(chunks)
        if not content.startswith(b"%PDF"):
            raise WritingRequirementSourceError("현재는 텍스트 PDF 원문만 자동 판독합니다.")
        text = extract_pdf_text(content)
        return GuideInspection(
            guide=guide,
            extracted_text=text,
            marker_contexts=marker_contexts(text),
            inspected_at=datetime.now(UTC),
        )
