"""기능2 — 이전 활동 기반 후속 탐구 추천 스키마."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.activity import ActivityType
from app.models.plan_item import PlanItemType


class FollowUpRequest(BaseModel):
    source_activity_id: uuid.UUID
    desired_activity_type: ActivityType | None = None
    note: str | None = None


class RecommendationOption(BaseModel):
    topic: str
    connection_reason: str
    subject_relevance: str
    career_relevance: str
    record_potential: str
    difficulty: Literal["easy", "medium", "hard"]
    materials: list[str] = []
    expected_output: str
    expansion_potential: str


class RecommendationDraft(BaseModel):
    options: list[RecommendationOption]


class RecommendationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_activity_id: uuid.UUID | None
    desired_activity_type: str | None
    options: list[RecommendationOption]
    created_at: datetime


class AdoptOptionRequest(BaseModel):
    """추천 선택지 하나를 계획으로 담는다 — 추천에서 끝나지 않고
    '추천 → 계획 → 실행 → 기록'으로 이어지게 하는 연결 고리."""

    option_index: int = 0
    item_type: PlanItemType = PlanItemType.ACTIVITY
    target_grade: int | None = None
    target_semester: int | None = None


class FeedbackCreate(BaseModel):
    """추천 선택지에 대한 반응. **append-only다** — 원래 추천 실행 기록을 덮어쓰지
    않고 다음 추천의 개인화 신호로만 쌓인다."""

    option_index: int = Field(ge=0)
    action: Literal["saved", "rejected"]
    reason: str | None = None


class FeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    recommendation_id: uuid.UUID
    option_index: int
    action: str
    reason: str | None
    created_at: datetime
