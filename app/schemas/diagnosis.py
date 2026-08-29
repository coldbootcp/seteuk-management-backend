from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from app.models.diagnosis import DiagnosisStatus


class PreQuestion(BaseModel):
    key: str
    prompt: str
    options: list[str] = []
    allow_custom: bool = True


class PreQuestionsResponse(BaseModel):
    questions: list[PreQuestion] = []


class PreQuestionAnswer(BaseModel):
    key: str
    prompt: str
    # Omitted/empty means the user skipped this particular question.
    answer: str | None = None


class PreQuestionAnswersRequest(BaseModel):
    answers: list[PreQuestionAnswer] = []


class SemesterSummary(BaseModel):
    grade: int
    semester: int
    summary: str
    standout_activities: list[str] = []


class DomainFeedback(BaseModel):
    domain: str
    feedback: str


class CareerThreadEntry(BaseModel):
    grade: int
    semester: int
    type: Literal["completed", "suggested"]
    theme: str
    source: str | None = None
    connection: str


class DiagnosisCreateResponse(BaseModel):
    diagnosis_id: UUID
    status: DiagnosisStatus


class DiagnosisStatusResponse(BaseModel):
    diagnosis_id: UUID
    status: DiagnosisStatus


class DiagnosisResult(BaseModel):
    diagnosis_id: UUID
    status: DiagnosisStatus
    semester_summaries: list[SemesterSummary] = []
    domain_feedback: list[DomainFeedback] = []
    career_thread: list[CareerThreadEntry] = []
    overall_summary: str | None = None
    strengths: list[str] = []
    weaknesses: list[str] = []
    career_gap_analysis: str | None = None
    keyword_map: list[str] = []


# --- Internal pipeline models (LLM structured-output targets, not exposed via API) ---


class SemesterSummaryDraft(BaseModel):
    """1단계 산출물 — grade/semester는 LLM이 아니라 파이프라인이 붙인다."""

    summary: str
    standout_activities: list[str] = []


class DomainFeedbackDraft(BaseModel):
    """2단계 산출물 — domain은 파이프라인이 붙인다."""

    feedback: str


class SynthesisResult(BaseModel):
    """3단계(종합) 산출물."""

    career_thread: list[CareerThreadEntry]
    overall_summary: str
    strengths: list[str]
    weaknesses: list[str]
    career_gap_analysis: str
    keyword_map: list[str]


class ExtractedInterest(BaseModel):
    field_key: str
    value: Any


class ExtractedInterestsResult(BaseModel):
    """사전질문 답변에서, 저장할 가치가 있다고 판단된 것만 담김(durability 필터)."""

    items: list[ExtractedInterest] = []
