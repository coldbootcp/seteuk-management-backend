"""지원처별 자소서 설계. 초안 본문보다 앞선, 학생이 확정한 근거 구조다."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class ApplicationPreparation(Base):
    __tablename__ = "application_preparations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    university_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("universities.id"), nullable=False
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admission_programs.id"), nullable=False
    )
    track_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admission_tracks.id"), nullable=True
    )
    admission_year: Mapped[int] = mapped_column(Integer, nullable=False)
    central_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 한 편의 글의 순서. 문장 초안이 아니라 근거를 배치하는 설계 메모다.
    narrative_outline: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ApplicationEvidence(Base):
    __tablename__ = "application_evidences"
    __table_args__ = (
        UniqueConstraint("preparation_id", "activity_id", name="uq_application_evidence_activity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    preparation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("application_preparations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    activity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("activities.id", ondelete="CASCADE"), nullable=False
    )
    narrative_role: Mapped[str] = mapped_column(String(40), nullable=False, default="exploration")
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    student_note: Mapped[str | None] = mapped_column(Text, nullable=True)
