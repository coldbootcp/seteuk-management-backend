import pytest

from app.services.writing_requirement_source import (
    WritingRequirementSourceError,
    extract_pdf_text,
    marker_contexts,
)


def test_marker_contexts_keeps_unique_evidence() -> None:
    text = "A" * 300 + " 자기소개서 제출 여부를 확인합니다. " + "B" * 300
    contexts = marker_contexts(text)
    assert len(contexts) == 1
    assert "자기소개서" in contexts[0]


def test_extract_pdf_text_rejects_non_pdf() -> None:
    with pytest.raises(WritingRequirementSourceError):
        extract_pdf_text(b"not a pdf")
