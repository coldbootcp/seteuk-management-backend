"""기능2 — 이전 활동 기반 후속 탐구 추천 스키마."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

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
