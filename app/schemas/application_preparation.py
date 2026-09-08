"""지원처별 학생부·면접 준비 API. 활동 근거는 서버가 소유한 목록으로 검증한다."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class EvidenceInput(BaseModel):
    activity_id: uuid.UUID
    narrative_role: str = Field(default="exploration", max_length=40)
    order_index: int = Field(default=0, ge=0, le=20)
    student_note: str | None = Field(default=None, max_length=1000)


class ApplicationPreparationCreate(BaseModel):
    university_id: uuid.UUID
    program_id: uuid.UUID
    track_id: uuid.UUID | None = None
    admission_year: int = Field(ge=2026, le=2035)


class ApplicationPreparationUpdate(BaseModel):
    central_question: str | None = Field(default=None, max_length=1000)
    narrative_outline: list[dict[str, str]] = Field(default_factory=list, max_length=6)
    evidence: list[EvidenceInput] = Field(default_factory=list, max_length=6)


class ActivityEvidenceRead(BaseModel):
    activity_id: uuid.UUID
    grade: int
    semester: int | None
    title: str
    subject: str | None
    description: str
    reflection: str | None
    attachment_count: int
    readiness: str
    missing_fields: list[str]
    narrative_role: str | None = None
    order_index: int | None = None
    student_note: str | None = None


class ActivityFlowRead(BaseModel):
    id: uuid.UUID | None
    title: str
    description: str | None
    activities: list[ActivityEvidenceRead]


class RankedActivityRead(BaseModel):
    activity_id: uuid.UUID
    rank: int
    reason: str
    readiness: str
    missing_fields: list[str]


class PreparationActivityRecommendationRead(BaseModel):
    activities: list[RankedActivityRead]
    gap_notice: str | None = None


class ApplicationPreparationRead(BaseModel):
    id: uuid.UUID
    university_id: uuid.UUID
    program_id: uuid.UUID
    track_id: uuid.UUID | None
    university_name: str
    program_name: str
    track_name: str | None
    admission_year: int
    central_question: str | None
    narrative_outline: list[dict[str, str]]
    evidence: list[ActivityEvidenceRead]
    created_at: datetime
    updated_at: datetime
