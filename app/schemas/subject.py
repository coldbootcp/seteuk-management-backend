"""과목 카탈로그 검색과 '이번 학기 수강 과목' 등록의 요청/응답."""

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.records import check_subject_code


class SubjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    curriculum: str
    group: str
    category: str
    default_units: int
    track: str | None = None
    # 공식 편제표와 직접 대조하지 못한 과목(예술 계열 등)은 false.
    verified: bool = True


class SubjectListResponse(BaseModel):
    # 이 학생이 적용받는 교육과정 — 화면이 "2022 개정" 같은 안내를 붙일 때 쓴다.
    curriculum: str
    items: list[SubjectRead]


CustomSubjectName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class CurrentCourseInput(BaseModel):
    """이번 학기 수강 과목 하나. 카탈로그 후보를 골랐으면 subject_code만, 목록에 없는
    학교 자체 과목이면 custom_name만 채운다. 둘 다 채우거나 둘 다 비우면 거부한다."""

    subject_code: str | None = None
    custom_name: CustomSubjectName | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "CurrentCourseInput":
        if (self.subject_code is None) == (self.custom_name is None):
            raise ValueError(
                "과목 목록에서 고르거나(subject_code) 기타 과목명(custom_name) 중 하나만 주세요"
            )
        check_subject_code(self.subject_code)
        return self


class CurrentCoursesRequest(BaseModel):
    courses: list[CurrentCourseInput] = Field(max_length=30)


class CurrentCourseRead(BaseModel):
    id: uuid.UUID
    subject: str
    subject_code: str | None
    category: str
    units: int | None
    # 카탈로그에 없어 학생이 직접 입력한 과목
    is_custom: bool
    # 성적·생기부 등 다른 경로로 이미 있던 행이라 이 화면에서 지울 수 없는 과목
    locked: bool


class CurrentCoursesResponse(BaseModel):
    grade: int
    semester: int
    curriculum: str
    courses: list[CurrentCourseRead]
