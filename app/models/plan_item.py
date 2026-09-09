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
    """미래 계획 한 건 — **실행 단위**다.

    로드맵과 계획은 서로 다른 층이고, 통합에서도 합치지 않기로 했다.

        roadmap_nodes        학기 서사 마디. 6개 고정. "이 학기에 무엇을 향해 가는가"
        roadmap_plan_events  그 마디가 제안하는 주제 후보. 학생이 고르는 목록
        plan_items           실제로 하기로 한 것. 개수 자유. 완료하면 기록이 된다
        activities           일어난 일

    마디로 계획을 대신할 수 없는 이유는 두 가지다. 마디는 6개로 고정인데 학생이
    세우는 계획은 개수가 자유롭고, 완료 승격(계획 → 기록)은 애초에 계획의 성질이지
    마디의 성질이 아니다. 그래서 계획은 남기고 `roadmap_node_id`로 마디에 매단다.

    기록과 계획을 한 테이블에 섞지 않는 원칙은 그대로다. 완료 처리하면 item_type에
    맞는 기록 행이 생성되고 completed_activity_id 등으로 연결되며,
    source_activity_id를 통해 '어떤 과거 활동의 후속인지'가 남는다."""

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
    # 이 계획이 어느 학기 마디를 위한 것인지. 로드맵 밖에서 세운 계획은 비어 있다 —
    # 마디에 매달리지 않는 계획도 얼마든지 유효하다.
    roadmap_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roadmap_nodes.id", ondelete="SET NULL"), nullable=True
    )
    # 이 계획이 어떤 제안 주제에서 나왔는지. 학생이 마디의 후보 목록에서 골라 담으면
    # 채워진다.
    source_plan_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roadmap_plan_events.id", ondelete="SET NULL"), nullable=True
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
