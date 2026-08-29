"""탭 관리(Phase 4) 리소스의 요청/응답 스키마.

각 리소스는 Create / Update(부분 수정) / Read 세 벌을 가진다. Read에는 읽기 전용
`source_upload_id`가 붙어 클라이언트가 "생기부에서 파싱된 행"과 "직접 입력한 행"을
구분할 수 있고, Create에는 없어서 사용자가 임의로 생기부발로 위장할 수 없다.
"""

import uuid

# `date`라는 이름의 필드가 있어서 별칭으로 임포트한다 — 클래스 본문에서
# `date: date_type | None = None`을 쓰면 값 대입이 먼저 일어나 타입 이름이 가려진다.
from datetime import date as date_type
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.activity import ActivityCategory, ActivityType


class ListResponse[T](BaseModel):
    items: list[T]
    total: int


class RecordBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # null이면 사용자가 직접 입력한 행 — 생기부 재업로드에도 지워지지 않는다.
    source_upload_id: uuid.UUID | None
    created_at: datetime


# --- 출결 ---------------------------------------------------------------


class AttendanceCreate(BaseModel):
    grade: int = Field(ge=1, le=3)
    total_days: int = Field(ge=0)
    absence: int = Field(default=0, ge=0)
    note: str | None = None


class AttendanceUpdate(BaseModel):
    grade: int | None = Field(default=None, ge=1, le=3)
    total_days: int | None = Field(default=None, ge=0)
    absence: int | None = Field(default=None, ge=0)
    note: str | None = None


class AttendanceRead(RecordBase):
    grade: int
    total_days: int
    absence: int
    note: str | None


# --- 교과 성적 ------------------------------------------------------------


class AcademicPerformanceCreate(BaseModel):
    grade: int = Field(ge=1, le=3)
    semester: int = Field(ge=1, le=2)
    category: str
    subject: str
    units: int | None = None
    achievement_grade: str | None = None
    student_count: int | None = None
    raw_score: float | None = None
    subject_average: float | None = None
    std_deviation: float | None = None
    rank: str | None = None


class AcademicPerformanceUpdate(BaseModel):
    grade: int | None = Field(default=None, ge=1, le=3)
    semester: int | None = Field(default=None, ge=1, le=2)
    category: str | None = None
    subject: str | None = None
    units: int | None = None
    achievement_grade: str | None = None
    student_count: int | None = None
    raw_score: float | None = None
    subject_average: float | None = None
    std_deviation: float | None = None
    rank: str | None = None


class AcademicPerformanceRead(RecordBase):
    grade: int
    semester: int
    category: str
    subject: str
    units: int | None
    achievement_grade: str | None
    student_count: int | None
    raw_score: float | None
    subject_average: float | None
    std_deviation: float | None
    rank: str | None


# --- 독서 활동 ------------------------------------------------------------


class ReadingActivityCreate(BaseModel):
    grade: int = Field(ge=1, le=3)
    semester: int | None = Field(default=None, ge=1, le=2)
    subject: str | None = None
    title: str
    author: str | None = None


class ReadingActivityUpdate(BaseModel):
    grade: int | None = Field(default=None, ge=1, le=3)
    semester: int | None = Field(default=None, ge=1, le=2)
    subject: str | None = None
    title: str | None = None
    author: str | None = None


class ReadingActivityRead(RecordBase):
    grade: int
    semester: int | None
    subject: str | None
    title: str
    author: str | None


# --- 수상 경력 ------------------------------------------------------------


class AwardCreate(BaseModel):
    name: str
    rank: str | None = None
    date: date_type | None = None
    raw_date: str | None = None


class AwardUpdate(BaseModel):
    name: str | None = None
    rank: str | None = None
    date: date_type | None = None
    raw_date: str | None = None


class AwardRead(RecordBase):
    name: str
    rank: str | None
    date: date_type | None
    raw_date: str | None


# --- 봉사 활동 ------------------------------------------------------------


class VolunteerRecordCreate(BaseModel):
    grade: int = Field(ge=1, le=3)
    date: date_type | None = None
    raw_date: str | None = None
    place: str | None = None
    content: str | None = None
    hours: int | None = Field(default=None, ge=0)


class VolunteerRecordUpdate(BaseModel):
    grade: int | None = Field(default=None, ge=1, le=3)
    date: date_type | None = None
    raw_date: str | None = None
    place: str | None = None
    content: str | None = None
    hours: int | None = Field(default=None, ge=0)


class VolunteerRecordRead(RecordBase):
    grade: int
    date: date_type | None
    raw_date: str | None
    place: str | None
    content: str | None
    hours: int | None


# --- 활동 ---------------------------------------------------------------


class ActivityCreate(BaseModel):
    grade: int = Field(ge=1, le=3)
    semester: int | None = Field(default=None, ge=1, le=2)
    activity_category: ActivityCategory
    subject: str | None = None
    activity_name: str
    activity_type: ActivityType = ActivityType.OTHER
    role: str | None = None
    description: str
    keywords: list[str] = []
    # 이 활동이 고도화한 이전 활동. 학생이 탭에서 직접 이어 붙이거나,
    # 계획 완료 처리 시 계획의 source_activity_id가 복사돼 들어온다.
    parent_activity_id: uuid.UUID | None = None


class ActivityUpdate(BaseModel):
    grade: int | None = Field(default=None, ge=1, le=3)
    semester: int | None = Field(default=None, ge=1, le=2)
    activity_category: ActivityCategory | None = None
    subject: str | None = None
    activity_name: str | None = None
    activity_type: ActivityType | None = None
    role: str | None = None
    description: str | None = None
    keywords: list[str] | None = None
    parent_activity_id: uuid.UUID | None = None


class ActivityRead(RecordBase):
    grade: int
    semester: int | None
    activity_category: str
    subject: str | None
    activity_name: str
    activity_type: str
    role: str | None
    description: str
    keywords: list[str]
    parent_activity_id: uuid.UUID | None
    parsing_confidence: float | None


class ActivityLineageNode(BaseModel):
    """계보 그래프의 한 마디. 과거 활동(activity)과 아직 실행되지 않은
    계획(plan)이 같은 사슬 위에 섞여 나타난다."""

    kind: str
    id: uuid.UUID
    title: str
    grade: int | None
    semester: int | None
    status: str
    parent_id: uuid.UUID | None


class ActivityLineageResponse(BaseModel):
    nodes: list[ActivityLineageNode]
