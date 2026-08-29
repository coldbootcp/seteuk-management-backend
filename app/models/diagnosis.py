import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class DiagnosisStatus(StrEnum):
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class Diagnosis(Base):
    __tablename__ = "diagnoses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DiagnosisStatus.PROCESSING.value
    )
    failure_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # 1단계 산출물 — 학기별 개별 요약
    semester_summaries: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # 2단계 산출물 — 분야별(성적/활동/수상/봉사/독서) 피드백
    domain_feedback: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # 3단계 산출물 — 과거(completed)+미래(suggested)가 하나로 이어진 진로 스토리
    career_thread: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    overall_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    strengths: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    weaknesses: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    career_gap_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    keyword_map: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
