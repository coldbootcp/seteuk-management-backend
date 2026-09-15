import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class ConsultationKind(StrEnum):
    """최초 상담은 백지에서 3개년 큰 계획을 세우고, 재평가는 학기가 바뀔 때마다
    강제되어 기존 큰 계획을 점검·조정한다."""

    INITIAL = "initial"
    SEMESTER_REVIEW = "semester_review"


class ConsultationStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    # 챗봇이 signal_ready_to_conclude를 호출한 상태. 대화가 이어지면 다시
    # IN_PROGRESS로 되돌아갈 수 있다(readiness는 매 턴 재평가된다).
    READY = "ready"
    CONCLUDED = "concluded"
    ABANDONED = "abandoned"


class ConsultationSession(Base):
    """진단+상담 관문의 판정 대상이자, 확정 전까지 큰 계획 초안을 담아두는 곳.
    확정(conclude)되기 전까지는 실제 roadmap_nodes/roadmap_plan_events를
    건드리지 않는다 — 학생이 나가기 버튼을 실제로 눌러야 비로소 반영된다."""

    __tablename__ = "consultation_sessions"
    __table_args__ = (
        Index("ix_consultation_sessions_user_status", "user_id", "status"),
        Index(
            "ix_consultation_sessions_user_period",
            "user_id",
            "kind",
            "target_grade",
            "target_semester",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    # 이 상담이 "확정 짓는" 학기 — 재평가는 학생이 새로 선언한 현재 학기,
    # 최초 상담은 가입 시점의 현재 학기.
    target_grade: Mapped[int] = mapped_column(Integer, nullable=False)
    target_semester: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ConsultationStatus.IN_PROGRESS.value
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    concluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 재평가에서 "전체 계획을 처음부터 다시 세우자"는 챗봇 제안에 학생이 명시
    # 동의한 시각. None이면 propose_draft_plan(mode=full_replan)이 거부된다.
    full_replan_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    draft_plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
