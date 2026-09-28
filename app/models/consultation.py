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
    강제되어 기존 큰 계획을 점검·조정한다. 졸업생(수시 재수생)은 생기부가 이미
    확정되어 새 계획을 세울 수 없으므로, 로드맵 대신 확정된 생기부와 목표 학과의
    적합성·지원 전략만 상담한다(graduate_fit)."""

    INITIAL = "initial"
    SEMESTER_REVIEW = "semester_review"
    GRADUATE_FIT = "graduate_fit"
    # 설정 탭에서 올린 생기부에 이상·충돌이 있을 때 학생에게 해명을 듣고 반영 방법을 정하는
    # 상담. 관문(학기 상담 완료 여부)과 무관하다 — 마쳐도 학기 상담을 대신하지 않는다.
    RECORD_REVIEW = "record_review"


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
    건드리지 않는다 — 학생이 "상담 마치고 메인 화면으로" 버튼을 실제로 눌러야 비로소 반영된다."""

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
    # 상담은 "3개년 흐름 → 이번 학기 목표 → 구체 주제" 순서로 좁혀 간다. 앞 단계가
    # 정해지지 않으면 다음 단계 도구가 거부된다(consultation_tools의 핸들러가 강제).
    # draft_flow: 현재 학기~3학년 2학기의 큰 흐름 초안(+지나간 학기는 회고 자리).
    draft_flow: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 학생이 화면의 확정 버튼으로 3개년 흐름에 동의한 시각. 대화 텍스트("좋아요")가
    # 아니라 confirm-flow 엔드포인트로만 기록된다. 흐름이 바뀌면 다시 None이 된다.
    flow_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 확정된 흐름 안에서 합의한 이번 학기 목표(current_node). 주제는 이 목표에서 나온다.
    semester_goal: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    draft_plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # record_review 전용: 확인 중인 생기부 업로드와 학생이 정한 반영 방법
    # (services/record_review_consultation.RecordDecisions).
    source_upload_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seteuk_uploads.id", ondelete="SET NULL"), nullable=True
    )
    record_decisions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
