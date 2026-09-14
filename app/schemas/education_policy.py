"""입학 연도 기준 교육·대입 제도 응답 스키마."""

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class EducationPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    title: str
    freshman_year_start: int
    freshman_year_end: int | None
    curriculum_name: str
    rank_grade_scale: int | None
    summary: str
    details: dict[str, Any]
    source_label: str
    source_url: str
    source_published_on: date | None
    verified_at: datetime | None


class AdmissionPolicyRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    admission_year_start: int | None
    admission_year_end: int | None
    category: str
    decision_scope: str
    title: str
    summary: str
    action_required: str | None
    source_label: str
    source_url: str
    source_published_on: date | None
    verified_at: datetime | None


class EducationPolicyResolutionRead(BaseModel):
    """현재 사용자에게 실제로 적용할 수 있는 기준만 묶어 돌려준다."""

    freshman_academic_year: int | None
    policy: EducationPolicyRead | None
    admission_rules: list[AdmissionPolicyRuleRead]
    needs_freshman_academic_year: bool
    message: str | None = None
