import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class PlanItemType(StrEnum):
    """어느 탭에 속한 계획인지. 활동/독서/수행평가처럼 완료 시 실제 기록 행으로
    승격되는 타입과, 성적 목표처럼 승격 대상이 없는 타입이 섞여 있다."""

    ACTIVITY = "activity"
    READING = "reading"
    ASSESSMENT = "assessment"
    GRADE = "grade"
    VOLUNTEER = "volunteer"
    AWARD = "award"
    OTHER = "other"


class PlanItemOrigin(StrEnum):
    USER = "user"
    AI_ROADMAP = "ai_roadmap"
    RECOMMENDATION = "recommendation"
    CHATBOT = "chatbot"


class PlanItemStatus(StrEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    DROPPED = "dropped"


class PlanItem(Base):
    """미래 계획 한 건. 기록(activities 등)과 계획을 한 테이블에 섞지 않고 분리해,
    아직 종류가 확정되지 않은 계획이나 학기 단위 로드맵도 표현할 수 있게 한다.
    완료 처리하면 item_type에 맞는 기록 행이 생성되고 completed_activity_id 등으로
    연결되며, source_activity_id를 통해 '어떤 과거 활동의 후속인지'가 남는다."""

    __tablename__ = "plan_items"
    __table_args__ = (
        Index("ix_plan_items_user_target", "user_id", "target_grade", "target_semester"),
        Index("ix_plan_items_user_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 학기 로드맵 상의 위치. 아직 시기를 못 정한 계획은 둘 다 null로 둔다.
    target_grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_semester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PlanItemStatus.PLANNED.value
    )
    origin: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PlanItemOrigin.USER.value
    )
    # 이 계획이 어떤 과거 활동에서 뻗어 나왔는지 — 3년 계보 추적의 계획 쪽 절반.
    source_activity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("activities.id", ondelete="SET NULL"), nullable=True
    )
    source_recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recommendations.id", ondelete="SET NULL"), nullable=True
    )
    # 완료 처리로 승격된 기록 행. item_type에 따라 둘 중 하나만 채워진다.
    completed_activity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("activities.id", ondelete="SET NULL"), nullable=True
    )
    completed_reading_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reading_activities.id", ondelete="SET NULL"), nullable=True
    )
    keywords: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
