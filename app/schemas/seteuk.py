import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

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
    # 프롬프트는 반드시 채우라고 하지만 실제로 빠뜨린 응답을 관측했다. 필수로 두면
    # 항목 하나 때문에 블록 전체(활동 수십 건)가 버려지므로, activity_type과 같은
    # 원칙으로 비워 두고 살린다 — 이름만 있는 활동이 아예 없는 것보다 낫다.
    description: str = ""
    keywords: list[str] = []
    activity_category: ActivityCategory | None = None

    @field_validator("description", mode="before")
    @classmethod
    def _tolerate_missing_description(cls, value: object) -> object:
        return "" if value is None else value

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
    # 학적사항이 밝힌 "1학년이었던 학년도". 날짜만 있는 기록(수상 등)을 학년-학기로
    # 옮기는 기준점이며, 반영할 때 사용자에 저장해 이후에도 쓴다.
    freshman_academic_year: int | None = None
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


class LatestUploadResponse(BaseModel):
    """가장 최근 업로드 하나. 화면을 다시 그릴 때 "지금 어디까지 와 있는가"를
    되찾기 위한 것이라, 상태 판단에 필요한 것만 담는다.

    업로드 id를 클라이언트가 기억하지 못해도 되게 하려는 것이 요점이다 — 파싱은
    몇 분 걸리는데 그 사이 새로고침하면 진행 중인 업로드를 통째로 잃었다.
    """

    upload_id: UUID
    status: UploadStatus
    file_name: str | None = None
    parsing_confidence: float | None = None
    imported_at: datetime.datetime | None = None
    failure_reason: str | None = None
    created_at: datetime.datetime


class ImportPeriodOverride(BaseModel):
    """학생이 검토 화면에서 직접 고친 시점.

    생기부의 세특은 과목당 한 덩어리로 쓰여 있어서 어느 활동이 몇 학기인지 문서가
    말해 주지 않는다. 파서는 근거 없이 학기를 지어내지 않고 비워 두므로, 그 자리를
    아는 사람은 학생뿐이다 — 검토 단계에서 고른 값을 그대로 받는다.
    """

    section: str
    index: int
    grade: int | None = Field(default=None, ge=1, le=3)
    semester: int | None = Field(default=None, ge=1, le=2)


class ImportSelectionRequest(BaseModel):
    """무엇을 반영할지. 각 항목은 결과 배열의 index 목록이고, 생략하면 그 영역 전체다 —
    학생이 몇 개만 빼는 것이 보통이라 '지정 안 하면 전부'가 자연스럽다."""

    attendance: list[int] | None = None
    academic_performance: list[int] | None = None
    reading_activities: list[int] | None = None
    awards: list[int] | None = None
    volunteer_records: list[int] | None = None
    activities: list[int] | None = None
    # 파싱 결과의 시점을 학생이 고친 것. 지정된 항목만 덮어쓴다.
    period_overrides: list[ImportPeriodOverride] = []


class ImportResultResponse(BaseModel):
    """영역별로 실제 몇 건이 들어갔는지."""

    imported: dict[str, int]
