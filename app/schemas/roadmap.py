import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RoadmapPlanEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    node_id: uuid.UUID
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
    """비우면 프로필(진로 희망·관심 키워드·현재 학년-학기)에서 그대로 가져온다."""

    focus: str | None = None
    career_track: str | None = None


class RoadmapNodeUpdate(BaseModel):
    """학생이 미리보기에서 직접 다듬는 값. 제안은 제안일 뿐이라 제목·목표를 고칠 수 있다."""

    title: str | None = None
    objective: str | None = None
    status: str | None = None
    candidate_subjects: list[str] | None = None
    competency_goals: list[str] | None = None
