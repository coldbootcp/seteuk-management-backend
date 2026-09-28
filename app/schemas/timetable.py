"""시간표 API 스키마.

시간표는 학생의 현재 수강 과목 정본이다. 과목이 여러 칸에 반복 배치되는 실제
시간표 형태를 보존하기 위해 칸 배열을 한 시간표에 함께 저장한다.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.records import check_subject_code


class TimetableSlotInput(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    course_name: str = Field(min_length=1, max_length=100)
    # 과목 카탈로그(app/services/subject_catalog.py)의 코드. 후보에서 고른 과목만 채워지고,
    # 목록에 없어 "기타"로 직접 적은 과목과 예전에 저장된 칸은 비어 있다.
    subject_code: str | None = Field(default=None, max_length=60)
    teacher: str | None = Field(default=None, max_length=100)
    room: str | None = Field(default=None, max_length=100)
    day: int = Field(ge=0, le=4)
    start_period: int = Field(ge=1, le=12)
    period_span: int = Field(default=1, ge=1, le=4)
    category: str = Field(default="일반선택", max_length=50)
    group: str = Field(default="기타", max_length=50)
    color_index: int = Field(default=0, ge=0, le=20)
    # 0은 학생이 아직 단위수를 확인하지 못한 '추후 입력' 상태다.
    units: int = Field(default=0, ge=0, le=10)
    is_career_related: bool = False

    _check_subject_code = field_validator("subject_code")(check_subject_code)


class TimetableWrite(BaseModel):
    # localStorage에서 옮겨 온 시간표에는 서버 UUID가 없다. 그 경우 새 행으로 만든다.
    id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=100)
    grade: int = Field(ge=1, le=3)
    semester: int = Field(ge=1, le=2)
    is_default: bool = False
    slots: list[TimetableSlotInput] = Field(default_factory=list, max_length=100)


class TimetableReplaceRequest(BaseModel):
    timetables: list[TimetableWrite] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def _one_default_per_period(self) -> "TimetableReplaceRequest":
        defaults: set[tuple[int, int]] = set()
        for timetable in self.timetables:
            if not timetable.is_default:
                continue
            period = (timetable.grade, timetable.semester)
            if period in defaults:
                raise ValueError("한 학기에는 기본 시간표를 하나만 지정할 수 있습니다")
            defaults.add(period)
        return self


class TimetableRead(TimetableWrite):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class TimetableListResponse(BaseModel):
    timetables: list[TimetableRead]
