"""지원처 선택기에만 쓰는 공개 카탈로그 응답."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UniversitySearchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    campus_name: str | None
    region: str | None
    source_url: str
    verified_at: datetime | None


class AdmissionRecruitmentStatisticRead(BaseModel):
    admission_year: int | None
    admission_period: str | None
    recruitment_count: int | None
    applicant_count: int | None


class AdmissionSelectionDistributionRead(BaseModel):
    admission_year: int | None
    selection_type: str | None
    recruitment_count: int | None


class AdmissionEmploymentRateRead(BaseModel):
    year: int | None
    rate: float | None


class AdmissionCompetitionRateRead(BaseModel):
    admission_year: int | None
    early_ratio: float | None
    regular_ratio: float | None


class UniversityAdmissionStatisticsRead(BaseModel):
    """대학 전체 공개 통계. 모집단위별 입결과 혼동하지 않도록 별도 응답으로 둔다."""

    source_admission_year: int
    source_url: str
    verified_at: datetime | None
    recruitment_and_applicants: list[AdmissionRecruitmentStatisticRead]
    selection_distribution: list[AdmissionSelectionDistributionRead]
    employment_rate: list[AdmissionEmploymentRateRead]
    competition_rate: list[AdmissionCompetitionRateRead]


class AdmissionUniversityGuideTableRead(BaseModel):
    """원문 표의 병합 셀까지 행렬로 펼친 값이다."""

    rows: list[list[str]]


class AdmissionUniversityGuideSectionRead(BaseModel):
    title: str
    paragraphs: list[str]
    tables: list[AdmissionUniversityGuideTableRead]
    # 2027 자료에 수시·정시만 먼저 올라오고 입시가이드가 뒤늦게 올라오는 경우처럼,
    # 섹션마다 가장 최근 공개본이 다를 수 있다. 화면이 이를 한 해 자료처럼
    # 오해하지 않도록 각 섹션의 기준 연도와 원문을 고정한다.
    source_admission_year: int
    source_url: str


class AdmissionUniversityGuideRead(BaseModel):
    """대학 공통 대입특징·입시가이드. 표시 시 기준 학년도를 반드시 함께 쓴다."""

    source_admission_year: int
    source_url: str
    verified_at: datetime | None
    sections: list[AdmissionUniversityGuideSectionRead]


class AdmissionProgramRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    admission_year: int
    name: str
    college_name: str | None
    source_url: str
    source_status: str
    verified_at: datetime | None


class AdmissionTrackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    admission_type: str | None
    recruitment_period: str | None
    has_document_review: bool | None
    has_interview: bool | None
    has_minimum_requirement: bool | None
    source_url: str
    source_status: str
    verified_at: datetime | None


class AdmissionTrackReferenceRead(BaseModel):
    source_admission_year: int
    source_url: str
    has_document_review: bool | None
    has_interview: bool | None
    has_minimum_requirement: bool | None
    summary: str


class AdmissionTrackDetailRead(BaseModel):
    source_admission_year: int
    source_url: str
    selection_method: str
    eligibility: str
    document_evaluation: str
    interview: str
    csat_minimum: str
    schedule: list[str]
    subject_tip: str
    notes: list[str]
    sections: list["AdmissionTrackDetailSectionRead"]


class AdmissionTrackDetailSectionRead(BaseModel):
    title: str
    description: str
    items: list[str]


class AdmissionResearchCardRead(BaseModel):
    title: str
    description: str
    items: list[str]
    source_label: str
    source_url: str
    source_admission_year: int | None = None
    is_service_interpretation: bool = False


class AdmissionTrackResearchRead(BaseModel):
    university_name: str
    program_name: str
    track_name: str
    cards: list[AdmissionResearchCardRead]


class AdmissionProgramOutcomeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    recruitment_period: str | None
    selection_type: str | None
    selection_name: str | None
    initial_recruitment_count: int | None
    transferred_recruitment_count: int | None
    final_recruitment_count: int | None
    competition_rate: float | None
    additional_admission_count: int | None
    metrics: dict[str, str]


class AdmissionProgramPastResultsRead(BaseModel):
    """현재 모집단위와 이름이 확인된 가장 최근 공개 입시결과.

    과거 결과는 합격선이나 지원 가능 여부의 확정값이 아니다. 화면에서 반드시
    source_admission_year를 함께 보여주도록 응답에 고정한다.
    """

    source_admission_year: int
    reference_program_name: str
    source_url: str
    outcomes: list[AdmissionProgramOutcomeRead]


class AdmissionProgramProfileSectionRead(BaseModel):
    title: str
    items: list[str]


class AdmissionProgramProfileRead(BaseModel):
    """이름이 정확히 맞는 과거 공개 학과 소개.

    교육목표·교육과정·진로는 과거 공개 자료라는 점을 응답 학년도로 분명히 한다.
    """

    source_admission_year: int
    reference_program_name: str
    academic_field: str | None
    recruitment_count: int | None
    early_competition_rate: float | None
    regular_competition_rate: float | None
    source_url: str
    sections: list[AdmissionProgramProfileSectionRead]
