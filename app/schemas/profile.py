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


# --- 온보딩 보조 — 학생이 빈 폼 앞에서 막히지 않도록 LLM이 후보를 낸다. 제안은
# 제안일 뿐이고, 저장되는 것은 학생이 확정한 값이다. ---


class SuggestRequest(BaseModel):
    career_goal: str


class SuggestResponse(BaseModel):
    majors: list[str] = []
    keywords: list[str] = []


class ClarifyQuestion(BaseModel):
    key: str
    label: str
    question: str
    why: str = ""
    selection_mode: Literal["single", "multiple"] = "single"
    options: list[str] = []


class ClarifyAnswer(BaseModel):
    """앞선 질문에 학생이 이미 준 답."""

    key: str
    question: str = ""
    answer: str


class ClarifyRequest(BaseModel):
    """지금까지 채운 값. 전부 선택이라 폼을 반쯤 채운 상태에서도 물어볼 수 있다.

    `answers`가 중요하다 — 이걸 빼고 부르면 학생이 방금 답한 것을 모른 채 같은 질문을
    다시 내서 온보딩이 끝나지 않는다.
    """

    name: str | None = None
    grade: int | None = None
    semester: int | None = None
    career_goal: str | None = None
    target_department: str | None = None
    interest_keywords: list[str] = []
    self_assessed_strengths: str | None = None
    self_assessed_weaknesses: str | None = None
    answers: list[ClarifyAnswer] = []


class ClarifyResponse(BaseModel):
    questions: list[ClarifyQuestion] = []
    # 더 물을 것이 없으면 questions가 비고 이 값이 true다. 화면은 그때 로드맵
    # 생성으로 넘어간다.
    complete: bool = False
