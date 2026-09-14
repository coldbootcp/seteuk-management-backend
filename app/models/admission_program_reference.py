"""어디가 공개 학과 정보와 전년도 모집·입시결과의 기준 행."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AdmissionProgramReference(Base):
    """연도별 어디가 학과 정보의 원천 행.

    현재 지원 카드의 모집단위와 전년도 입시결과는 명칭·모집단위 개편으로 하나로
    고정할 수 없다. 따라서 대학·학년도·어디가 학과코드를 우선 식별자로 보관한다.
    """

    __tablename__ = "admission_program_references"
    __table_args__ = (
        UniqueConstraint(
            "university_id",
            "source_admission_year",
            "source_reference_code",
            name="uq_admission_program_reference_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    university_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("universities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_admission_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_reference_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    academic_field: Mapped[str | None] = mapped_column(String(80), nullable=True)
    recruitment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    early_competition_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    regular_competition_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 상세 학과 페이지의 교육목표·교육과정·진로 등은 표의 형태가 학교마다 달라
    # 제목과 항목 목록을 가진 JSON으로 정규화한다. 공개되지 않은 섹션은 null이다.
    detail_sections: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # 공개 결과·학과 소개가 빈 경우에도 원천을 실제 확인했다는 사실을 남긴다.
    # 이 값이 없을 때만 대량 수집기가 재시도하므로, 중단 후 빈 응답을 끝없이
    # 다시 요청하거나 이미 수집한 대형 대학 결과를 지우는 일을 막는다.
    outcomes_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    profile_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AdmissionProgramOutcome(Base):
    """한 학과의 전형별 공개 입시결과 한 행.

    성적 지표의 의미와 공개 범위는 대학별로 달라서, 공통 수치와 나머지 열을
    ``metrics``에 함께 보존한다. 점수 종류를 섞어 단일 '커트라인'으로 만들지 않는다.
    """

    __tablename__ = "admission_program_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    program_reference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admission_program_references.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recruitment_period: Mapped[str | None] = mapped_column(String(40), nullable=True)
    selection_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    selection_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    initial_recruitment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transferred_recruitment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_recruitment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    competition_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    additional_admission_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
