import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RoadmapPlanEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    node_id: uuid.UUID
    order_index: int
    month_day: str
    category: str
    subject: str
    # core는 그 학기에 남겨야 할 축, optional은 학교 기회가 맞을 때 고르는 확장.
    priority: str
    title: str
    description: str


class RoadmapNodeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_index: int
    grade: int
    semester: int
    narrative_stage: str
    title: str
    objective: str
    candidate_subjects: list[str]
    competency_goals: list[str]
    status: str
    instantiated_activity_id: uuid.UUID | None
    plan_events: list[RoadmapPlanEventRead] = []


class RoadmapRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    career_track: str
    template_id: str
    status: str
    created_at: datetime
    nodes: list[RoadmapNodeRead] = []


class RoadmapGenerateRequest(BaseModel):
    """비우면 프로필(진로 희망·관심 키워드·현재 학년-학기)에서 그대로 가져온다.

    온보딩 미리보기는 프로필을 저장하기 **전에** 로드맵을 만들어 보여준다. 그래서
    학년·학기까지 받을 수 있어야 한다 — 안 그러면 저장 전 기본값(1학년 1학기)으로
    활성 마디가 잡혀, 2학년 학생이 1학년 1학기를 현재로 보는 로드맵을 받는다.
    """

    focus: str | None = None
    career_track: str | None = None
    grade: int | None = Field(default=None, ge=1, le=3)
    semester: int | None = Field(default=None, ge=1, le=2)


class RoadmapNodeUpdate(BaseModel):
    """학생이 미리보기에서 직접 다듬는 값. 제안은 제안일 뿐이라 제목·목표를 고칠 수 있다."""

    title: str | None = None
    objective: str | None = None
    status: str | None = None
    candidate_subjects: list[str] | None = None
    competency_goals: list[str] | None = None


class ReconciliationLogRead(BaseModel):
    """활동이 로드맵의 어디에 해당하는지에 대한 판정 한 건. 덮어쓰지 않고 쌓이므로
    화면은 활동 타임라인과 함께 이력으로 보여줄 수 있다."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    activity_id: uuid.UUID | None
    roadmap_id: uuid.UUID
    node_id: uuid.UUID | None
    match_type: str
    rationale: str
    action: str
    confidence: int
    created_at: datetime


class NodeSummaryDraft(BaseModel):
    """LLM이 돌려주는 마디 요약."""

    summary: str


class NodeSummaryResponse(BaseModel):
    summary: str


class ActivityReviewDraft(BaseModel):
    """LLM이 돌려주는 활동 검토."""

    alignment: Literal["aligned", "partial", "separate"] = "separate"
    summary: str = ""
    evidence: list[str] = []
    gaps: list[str] = []
    next_steps: list[str] = []


class ActivityReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    activity_id: uuid.UUID
    roadmap_node_id: uuid.UUID | None
    alignment: str
    summary: str
    evidence: list[str]
    gaps: list[str]
    next_steps: list[str]
    provider: str
    created_at: datetime
