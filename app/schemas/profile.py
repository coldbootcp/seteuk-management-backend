from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class FieldKey(StrEnum):
    CAREER_GOAL = "career_goal"
    TARGET_DEPARTMENT = "target_department"
    INTEREST_KEYWORDS = "interest_keywords"
    CAREER_SPECIFICITY = "career_specificity"
    PREFERRED_OUTPUT_TYPES = "preferred_output_types"
    ACTIVITY_CHANNELS = "activity_channels"
    ROADMAP_CONSTRAINTS = "roadmap_constraints"
    SELF_ASSESSED_STRENGTHS = "self_assessed_strengths"
    SELF_ASSESSED_WEAKNESSES = "self_assessed_weaknesses"


class CareerGoal(BaseModel):
    goal: str
    note: str | None = None


class CareerSpecificity(BaseModel):
    level: Literal["broad", "specific"]
    known_concepts: list[str] = []
    curious_topics: list[str] = []


class ProfileRequest(BaseModel):
    name: str
    grade: int
    semester: int
    # 생기부가 없어서 학적사항을 읽을 수 없는 경우에도 교육과정·등급제를 정확히
    # 판정하기 위해 온보딩에서 한 번 받는다. 이후 날짜로 추정하지 않는다.
    freshman_academic_year: int | None = Field(default=None, ge=1990, le=2100)
    career_goal: CareerGoal
    target_department: str
    interest_keywords: list[str]
    career_specificity: CareerSpecificity
    preferred_output_types: list[str]
    activity_channels: list[str]
    roadmap_constraints: str | None = None
    self_assessed_strengths: str
    self_assessed_weaknesses: str


class ProfileResponse(BaseModel):
    name: str | None = None
    grade: int | None = None
    semester: int | None = None
    freshman_academic_year: int | None = None
    career_goal: CareerGoal | None = None
    target_department: str | None = None
    interest_keywords: list[str] = []
    career_specificity: CareerSpecificity | None = None
    preferred_output_types: list[str] = []
    activity_channels: list[str] = []
    roadmap_constraints: str | None = None
    self_assessed_strengths: str | None = None
    self_assessed_weaknesses: str | None = None


# --- 온보딩 보조 — 학생이 빈 폼 앞에서 막히지 않도록 LLM이 후보를 낸다. 제안은
# 제안일 뿐이고, 저장되는 것은 학생이 확정한 값이다. ---


class SuggestRequest(BaseModel):
    career_goal: str


class SuggestResponse(BaseModel):
    majors: list[str] = []
    keywords: list[str] = []



