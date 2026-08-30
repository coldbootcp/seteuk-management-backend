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


# --- 성적 추이 섹션 — LLM을 거치지 않는 순수 데이터. 프론트가 그래프로 그린다. ---


class GradesTrendPoint(BaseModel):
    grade: int
    semester: int
    achievement_grade: str | None = None
    raw_score: float | None = None
    subject_average: float | None = None
    std_deviation: float | None = None
    rank: str | None = None


class GradesTrendSubject(BaseModel):
    subject: str
    category: str
    points: list[GradesTrendPoint]


class GradesTrendOverallPoint(BaseModel):
    grade: int
    semester: int
    average_raw_score: float | None = None
    subject_count: int


class GradesTrend(BaseModel):
    subjects: list[GradesTrendSubject] = []
    overall: list[GradesTrendOverallPoint] = []


# --- 학기별 평가 섹션 — 학기당 1회 LLM 호출, 성적/독서/활동 3개 독립 텍스트 ---


class SemesterReview(BaseModel):
    grade: int
    semester: int
    grades_review: str
    reading_review: str
    activities_review: str


# --- 진로 유기적 평가 섹션 — 활동/수상/봉사를 아우르는 하나의 사슬(완료+제안) ---


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
    grades_trend: GradesTrend | None = None
    semester_reviews: list[SemesterReview] = []
    career_thread: list[CareerThreadEntry] = []
    # 종합 평가 — semester_reviews와 career_thread의 결과만 입력받아 생성된다
    # (원본 데이터 재조회 없음). unrecorded_points는 "지금까지 기록되지 않았지만
    # 이 진로라면 있어야 할 것들"이다.
    strengths: list[str] = []
    weaknesses: list[str] = []
    unrecorded_points: list[str] = []


# --- Internal pipeline models (LLM structured-output targets, not exposed via API) ---


class SemesterReviewDraft(BaseModel):
    """학기별 평가 산출물 — grade/semester는 LLM이 아니라 파이프라인이 붙인다."""

    grades_review: str
    reading_review: str
    activities_review: str


class CareerThreadDraft(BaseModel):
    career_thread: list[CareerThreadEntry]


class OverallAssessmentDraft(BaseModel):
    """종합 평가 산출물 — semester_reviews/career_thread만 입력받아 생성된다."""

    strengths: list[str]
    weaknesses: list[str]
    unrecorded_points: list[str]


class ExtractedInterest(BaseModel):
    field_key: str
    value: Any


class ExtractedInterestsResult(BaseModel):
    """사전질문 답변에서, 저장할 가치가 있다고 판단된 것만 담김(durability 필터)."""

    items: list[ExtractedInterest] = []
