"""계획(plan_items) — 로드맵과 각 탭의 '앞으로 할 일' 스키마."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.activity import ActivityCategory, ActivityType
from app.models.plan_item import PlanItemStatus, PlanItemType


class PlanItemCreate(BaseModel):
    item_type: PlanItemType
    title: str
    description: str | None = None
    subject: str | None = None
    target_grade: int | None = Field(default=None, ge=1, le=3)
    target_semester: int | None = Field(default=None, ge=1, le=2)
    due_date: date | None = None
    keywords: list[str] = []
    # 이 계획이 어떤 과거 활동의 후속인지 / 어떤 추천에서 골라 담은 것인지.
    source_activity_id: uuid.UUID | None = None
    source_recommendation_id: uuid.UUID | None = None


class PlanItemUpdate(BaseModel):
    item_type: PlanItemType | None = None
    title: str | None = None
    description: str | None = None
    subject: str | None = None
    target_grade: int | None = Field(default=None, ge=1, le=3)
    target_semester: int | None = Field(default=None, ge=1, le=2)
    due_date: date | None = None
    keywords: list[str] | None = None
    status: PlanItemStatus | None = None
    source_activity_id: uuid.UUID | None = None


class PlanItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_type: str
    title: str
    description: str | None
    subject: str | None
    target_grade: int | None
    target_semester: int | None
    due_date: date | None
    status: str
    origin: str
    source_activity_id: uuid.UUID | None
    source_recommendation_id: uuid.UUID | None
    completed_activity_id: uuid.UUID | None
    completed_reading_id: uuid.UUID | None
    keywords: list[str]
    created_at: datetime
    updated_at: datetime


class PlanItemCompleteRequest(BaseModel):
    """계획을 실제 기록으로 승격시킬 때의 보정값. 비워두면 계획에 적힌 값과
    사용자의 현재 학년/학기로 채운다."""

    grade: int | None = Field(default=None, ge=1, le=3)
    semester: int | None = Field(default=None, ge=1, le=2)
    activity_category: ActivityCategory | None = None
    activity_type: ActivityType | None = None
    description: str | None = None
    author: str | None = None


class PlanItemCompleteResponse(BaseModel):
    plan_item: PlanItemRead
    created_activity_id: uuid.UUID | None = None
    created_reading_id: uuid.UUID | None = None


class RoadmapGenerateRequest(BaseModel):
    """어느 구간의 로드맵을 짤지. 비우면 사용자의 현재 학기 다음부터 3학년
    2학기까지 남은 전 구간을 대상으로 한다."""

    until_grade: int | None = Field(default=None, ge=1, le=3)
    until_semester: int | None = Field(default=None, ge=1, le=2)
    focus: str | None = None
    replace_existing: bool = True


class RoadmapSemester(BaseModel):
    grade: int = Field(ge=1, le=3)
    semester: int = Field(ge=1, le=2)
    theme: str
    rationale: str
    items: list["RoadmapDraftItem"]


class RoadmapDraftItem(BaseModel):
    item_type: PlanItemType
    title: str
    description: str
    subject: str | None = None
    keywords: list[str] = []
    # LLM이 "이 계획은 과거의 어떤 활동을 잇는다"고 판단했을 때 채워지는 활동 id.
    # 프롬프트에 넘긴 목록 밖의 값이면 서비스에서 버린다.
    source_activity_id: uuid.UUID | None = None


class RoadmapDraft(BaseModel):
    semesters: list[RoadmapSemester]


class RoadmapResponse(BaseModel):
    semesters: list[RoadmapSemester]
    created_plan_items: list[PlanItemRead]


# --- 3개년 그랜드 로드맵 조립 — 새 LLM 호출 없이, 이미 있는 진단(career_thread)과
# 계획(plan_items)을 과거/현재/미래 마일스톤 형태로 재배치만 한다. ---


class RoadmapOverviewPast(BaseModel):
    grade: int = Field(ge=1, le=3)
    # 그 학년의 career_thread completed 노드 theme들을 이어 붙인 한 줄 요약.
    summary: str
    themes: list[str]


class RoadmapOverviewCurrent(BaseModel):
    grade: int | None
    semester: int | None
    # 진단 종합 평가(SWOT)의 headline_comment를 그대로 재사용 — 가장 시급한 것 하나.
    headline_comment: str | None
    weaknesses: list[str]


class RoadmapOverviewFutureMilestone(BaseModel):
    grade: int = Field(ge=1, le=3)
    semester: int = Field(ge=1, le=2)
    # career_thread suggested 노드가 있으면 그 theme, 없으면 null.
    theme: str | None
    # 그 학기에 배정된 계획 제목들(plan_items).
    plan_titles: list[str]


class RoadmapOverview(BaseModel):
    past: list[RoadmapOverviewPast]
    current: RoadmapOverviewCurrent
    future: list[RoadmapOverviewFutureMilestone]
