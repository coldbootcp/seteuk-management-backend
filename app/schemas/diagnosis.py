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
    # 자율활동/진로활동/행동특성및종합의견처럼 학년 단위로만 존재하고 학기가
    # 없는 근거를 든 노드는 semester가 null일 수 있다(실제 DeepSeek 응답에서
    # 발생 — 필수로 두면 그런 노드가 하나만 있어도 진단 전체가 실패한다).
    semester: int | None = None
    type: Literal["completed", "suggested"]
    theme: str
    source: str | None = None
    connection: str


# --- 활동 인벤토리 섹션 — 활동을 역량 축으로 분류(필터링 없음, 전량 커버 목표) ---


class ActivityInventoryEntry(BaseModel):
    activity_id: UUID
    grade: int
    semester: int | None
    competency: Literal["전공관련교과역량", "진로역량", "공동체역량"]
    depth_level: Literal["단순참여", "탐구시도", "심화탐구"]
    headline: str


# --- 지식 그래프 섹션 — 과목/키워드 겹침으로 추린 후보 중 LLM이 확정한 융합 링크 ---


class KnowledgeGraphLink(BaseModel):
    from_activity_id: UUID
    to_activity_id: UUID
    link_type: Literal["vertical", "horizontal"]
    relation_label: str


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
    activity_inventory: list[ActivityInventoryEntry] = []
    knowledge_graph_links: list[KnowledgeGraphLink] = []
    # 종합 평가 — semester_reviews/career_thread/activity_inventory의 결과만
    # 입력받아 생성된다(원본 데이터 재조회 없음).
    #   strengths/weaknesses: 이미 드러난 내부 강점/약점.
    #   opportunities: 아직 기록에 없지만 남은 기간에 채우면 강점이 될 수 있는 것.
    #   threats: 외부 입시 환경이 아니라(그런 데이터가 없다) 반복되거나 악화되는
    #     내부 패턴 — 방치하면 굳어질 위험 신호.
    strengths: list[str] = []
    weaknesses: list[str] = []
    opportunities: list[str] = []
    threats: list[str] = []
    # SWOT 중 가장 시급한 것 하나를 짚는 1~3문장 — 새 사실을 지어내지 않고
    # 위 SWOT 항목 중 하나를 근거로 든다.
    headline_comment: str | None = None


# --- Internal pipeline models (LLM structured-output targets, not exposed via API) ---


class SemesterReviewDraft(BaseModel):
    """학기별 평가 산출물 — grade/semester는 LLM이 아니라 파이프라인이 붙인다."""

    grades_review: str
    reading_review: str
    activities_review: str


class CareerThreadDraft(BaseModel):
    career_thread: list[CareerThreadEntry]


class ActivityInventoryDraftEntry(BaseModel):
    """활동 인벤토리 산출물 한 건. UUID를 그대로 베끼게 하면 한 글자만 틀려도
    파싱이 깨지므로, LLM에게는 그 호출 안에서만 유효한 정수 index를 준다 —
    실제 activity_id로의 변환은 파이프라인이 index로 역참조해서 처리한다."""

    index: int
    competency: Literal["전공관련교과역량", "진로역량", "공동체역량"]
    depth_level: Literal["단순참여", "탐구시도", "심화탐구"]
    headline: str


class ActivityInventoryDraft(BaseModel):
    """활동 인벤토리 산출물 — 배치 하나(보통 학년 단위)에 대한 분류 결과."""

    entries: list[ActivityInventoryDraftEntry]


class KnowledgeGraphDraftLink(BaseModel):
    """지식 그래프 산출물 한 건 — activity_id 대신 index로 참조한다(위와 같은 이유)."""

    from_index: int
    to_index: int
    link_type: Literal["vertical", "horizontal"]
    relation_label: str


class KnowledgeGraphDraft(BaseModel):
    """지식 그래프 산출물 — 후보 쌍 중 실제로 의미 있다고 확정된 것만 담김."""

    links: list[KnowledgeGraphDraftLink]


class OverallAssessmentDraft(BaseModel):
    """종합 평가 산출물 — semester_reviews/career_thread/activity_inventory만
    입력받아 생성된다."""

    strengths: list[str]
    weaknesses: list[str]
    opportunities: list[str]
    threats: list[str]
    headline_comment: str


class ExtractedInterest(BaseModel):
    field_key: str
    value: Any


class ExtractedInterestsResult(BaseModel):
    """사전질문 답변에서, 저장할 가치가 있다고 판단된 것만 담김(durability 필터)."""

    items: list[ExtractedInterest] = []
