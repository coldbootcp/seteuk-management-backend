import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator

from app.models.activity import ActivityCategory, ActivityType
from app.models.seteuk_upload import UploadStatus


class AttendanceItem(BaseModel):
    grade: int
    total_days: int
    absence: int
    note: str | None = None


class AcademicPerformanceItem(BaseModel):
    grade: int
    semester: int
    category: str
    subject: str
    units: int | None = None
    achievement_grade: str | None = None
    student_count: int | None = None
    raw_score: float | None = None
    subject_average: float | None = None
    std_deviation: float | None = None
    rank: str | None = None


class ReadingActivityItem(BaseModel):
    grade: int
    semester: int | None = None
    subject: str | None = None
    title: str
    author: str | None = None


class AwardItem(BaseModel):
    name: str
    rank: str | None = None
    date: datetime.date | None = None
    raw_date: str | None = None
    # 참가대상 원문("3학년(216명)" 등)과 거기서 읽어낸 학년-학기.
    participants: str | None = None
    grade: int | None = None
    semester: int | None = None


class VolunteerRecordItem(BaseModel):
    grade: int
    date: datetime.date | None = None
    raw_date: str | None = None
    place: str | None = None
    content: str | None = None
    hours: int | None = None


class ActivityItem(BaseModel):
    grade: int
    semester: int | None = None
    activity_category: ActivityCategory
    subject: str | None = None
    activity_name: str
    activity_type: ActivityType
    role: str | None = None
    description: str
    keywords: list[str] = []
    source_block: str | None = None
    # Always null — see docs/PARSER_SPEC.md (confidence scoring out of scope).
    parsing_confidence: float | None = None


class LLMActivityDraft(BaseModel):
    """Subset of ActivityItem the LLM is responsible for; the pipeline fills in
    grade/semester/subject/source_block from the block's own metadata."""

    activity_name: str
    activity_type: ActivityType
    role: str = ""
    description: str
    keywords: list[str] = []
    activity_category: ActivityCategory | None = None

    @field_validator("activity_type", mode="before")
    @classmethod
    def _coerce_unknown_activity_type(cls, value: object) -> object:
        # DeepSeek occasionally invents a value outside the prompt's enum (e.g.
        # "lecture", "writing") despite being told the exact allowed set. Falling
        # back to OTHER keeps the rest of a valid draft instead of losing the whole
        # block over one field — see docs/PARSER_SPEC.md 2.5 on block-level tolerance.
        if isinstance(value, str) and value not in {t.value for t in ActivityType}:
            return ActivityType.OTHER
        return value


class LLMActivityDraftList(BaseModel):
    items: list[LLMActivityDraft]


class ParseError(BaseModel):
    block_id: str
    reason: str


class SeteukAnalysisResult(BaseModel):
    attendance: list[AttendanceItem] = []
    academic_performance: list[AcademicPerformanceItem] = []
    reading_activities: list[ReadingActivityItem] = []
    awards: list[AwardItem] = []
    volunteer_records: list[VolunteerRecordItem] = []
    activities: list[ActivityItem] = []
    errors: list[ParseError] = []


class UploadCreateResponse(BaseModel):
    upload_id: UUID
    status: UploadStatus


class UploadStatusResponse(BaseModel):
    status: UploadStatus
    parsing_confidence: float | None = None
    # 실제로 기록에 반영된 시점. 파싱만 끝나고 아직 검토 중이면 null이다.
    imported_at: datetime.datetime | None = None


class ImportSelectionRequest(BaseModel):
    """무엇을 반영할지. 각 항목은 결과 배열의 index 목록이고, 생략하면 그 영역 전체다 —
    학생이 몇 개만 빼는 것이 보통이라 '지정 안 하면 전부'가 자연스럽다."""

    attendance: list[int] | None = None
    academic_performance: list[int] | None = None
    reading_activities: list[int] | None = None
    awards: list[int] | None = None
    volunteer_records: list[int] | None = None
    activities: list[int] | None = None


class ImportResultResponse(BaseModel):
    """영역별로 실제 몇 건이 들어갔는지."""

    imported: dict[str, int]
