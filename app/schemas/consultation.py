import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConsultationStatusResponse(BaseModel):
    """관문 판정 결과. 프론트는 이 하나만 보고 게이트를 그릴지 결정한다."""

    satisfied: bool
    required_kind: Literal["initial", "semester_review"] | None = None
    target_grade: int | None = None
    target_semester: int | None = None
    resumable_session_id: uuid.UUID | None = None


class ConsultationSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    kind: str
    target_grade: int
    target_semester: int
    status: str
    ready: bool = False
    full_replan_confirmed: bool = False


class ConfirmFullReplanRequest(BaseModel):
    confirmed: bool


class ConsultationMessageCreate(BaseModel):
    content: str = Field(min_length=1)


class DraftNode(BaseModel):
    """propose_draft_plan 도구가 mode=full_replan일 때 채우는 마디 하나.
    RoadmapNode의 편집 가능 필드와 같은 shape."""

    grade: int = Field(ge=1, le=3)
    semester: int = Field(ge=1, le=2)
    narrative_stage: str
    title: str
    objective: str
    candidate_subjects: list[str] = []
    competency_goals: list[str] = []


class DraftPlanEvent(BaseModel):
    """RoadmapPlanEvent 편집 가능 필드와 같은 shape. 현재 마디에 대해 정확히
    10개(core 4 + optional 6 권장)를 상담에서 직접 만든다."""

    order_index: int
    month_day: str
    category: str = ""
    subject: str = ""
    priority: Literal["core", "optional"] = "core"
    title: str
    description: str = ""


class DraftCurrentNode(BaseModel):
    title: str
    objective: str
    candidate_subjects: list[str] = []
    competency_goals: list[str] = []


class DraftPlan(BaseModel):
    mode: Literal["full_replan", "current_node_only"]
    career_track: str = ""
    focus: str = ""
    nodes: list[DraftNode] = []
    current_node: DraftCurrentNode
    plan_events: list[DraftPlanEvent]
