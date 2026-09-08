"""입학연도별 대학·모집단위·전형 카탈로그.

학생의 지원 희망과 분리된 공용 기준 데이터다. 전형은 매년 달라지므로 모집단위와
전형 모두 admission_year에 매단다. 외부 원천을 다시 수집해도 과거 지원 카드가
무슨 기준을 보고 만들어졌는지 잃지 않도록, 출처와 자료 상태도 행마다 보관한다.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class University(Base):
    __tablename__ = "universities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    official_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    campus_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    region: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AdmissionProgram(Base):
    __tablename__ = "admission_programs"
    __table_args__ = (
        UniqueConstraint(
            "university_id", "admission_year", "name", name="uq_admission_program_year"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    university_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("universities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    admission_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # 대입정보포털의 공통 모집단위 코드. 이름이 바뀌거나 주·야간 표기가 달라도
    # 해당 연도의 원천 항목을 안전하게 갱신할 수 있게 한다.
    source_program_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    college_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_status: Mapped[str] = mapped_column(String(20), nullable=False, default="plan")
    is_recruiting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AdmissionTrack(Base):
    __tablename__ = "admission_tracks"
    __table_args__ = (UniqueConstraint("program_id", "name", name="uq_admission_track_program"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admission_programs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    admission_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    recruitment_period: Mapped[str | None] = mapped_column(String(40), nullable=True)
    has_document_review: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_interview: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_minimum_requirement: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_status: Mapped[str] = mapped_column(String(20), nullable=False, default="plan")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
