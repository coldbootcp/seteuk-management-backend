from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


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
    career_goal: CareerGoal | None = None
    target_department: str | None = None
    interest_keywords: list[str] = []
    career_specificity: CareerSpecificity | None = None
    preferred_output_types: list[str] = []
    activity_channels: list[str] = []
    roadmap_constraints: str | None = None
    self_assessed_strengths: str | None = None
    self_assessed_weaknesses: str | None = None
