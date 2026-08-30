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

    # 4단계 산출물 — 위 구조화 필드들을 사용자에게 그대로 보여주면 데이터 덤프처럼
    # 읽히므로, 챗봇과 같은 목소리로 하나의 글로 엮은 리포트를 별도로 저장해 둔다.
    # 3단계 결과만 입력받으므로(원본 데이터 재조회 없음) 추가 비용은 진단당 1회뿐이고,
    # 조회할 때마다 문구가 바뀌지 않아 사용자가 매번 같은 내용을 다시 읽을 수 있다.
    narrative_report: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
