import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class RoadmapStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    # 재생성하면 이전 버전은 지우지 않고 이 상태로 남긴다 — 실행 기록을 덮어쓰지
    # 않는다는 원칙 때문이다.
    SUPERSEDED = "superseded"


class RoadmapNodeStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    PARTIAL = "partial"
    DONE = "done"
    SKIPPED = "skipped"


class MatchType(StrEnum):
    """활동을 저장할 때 활성 노드와 대조한 판정."""

    MATCH = "MATCH"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    DIVERGE = "DIVERGE"
    # 학기 체크포인트까지 완료 활동이 없을 때. 활동 저장이 아니라 시간 기반
    # 이벤트라 별도로 만들어진다.
    MISS = "MISS"
    UNCLASSIFIABLE = "UNCLASSIFIABLE"


class Roadmap(Base):
    """3개년 로드맵 한 버전. 진로가 바뀌면 새 버전을 만들고 이전 것은 superseded로
    남긴다."""

    __tablename__ = "roadmaps"
    __table_args__ = (Index("ix_roadmaps_user_status", "user_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    career_track: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # 어느 서사 템플릿에서 개인화됐는지(예: semiconductor-narrative-v1).
    template_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RoadmapStatus.ACTIVE.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RoadmapNode(Base):
    """로드맵의 학기 단위 마디. 서사 단계(탐색/기초/연결/분화/…)를 갖고, 실제 활동으로
    옮겨지면 instantiated_activity_id가 채워진다."""

    __tablename__ = "roadmap_nodes"
    __table_args__ = (
        Index("ix_roadmap_nodes_roadmap_order", "roadmap_id", "order_index"),
        Index("ix_roadmap_nodes_user_period", "user_id", "grade", "semester"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    roadmap_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roadmaps.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    semester: Mapped[int] = mapped_column(Integer, nullable=False)
    narrative_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    candidate_subjects: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    competency_goals: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RoadmapNodeStatus.PENDING.value
    )
    instantiated_activity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("activities.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RoadmapPlanEvent(Base):
    """노드 안의 월/일 단위 실행 이벤트 — "언제 무엇을 한다"까지 내려온 계획."""

    __tablename__ = "roadmap_plan_events"
    __table_args__ = (Index("ix_roadmap_plan_events_node", "node_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    roadmap_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roadmaps.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roadmap_nodes.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # "03-15"처럼 연도 없는 월-일. 학년이 노드에 있으므로 연도는 중복이다.
    month_day: Mapped[str] = mapped_column(String(10), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReconciliationLog(Base):
    """활동과 로드맵을 대조한 판정 이력. 덮어쓰지 않고 쌓기만 한다 — 판단이 왜 그렇게
    났는지 나중에 되짚을 수 있어야 하기 때문이다."""

    __tablename__ = "reconciliation_logs"
    __table_args__ = (Index("ix_reconciliation_logs_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # MISS는 활동 없이 발생하는 체크포인트 이벤트라 activity_id가 비어 있을 수 있다.
    activity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("activities.id", ondelete="CASCADE"), nullable=True
    )
    roadmap_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roadmaps.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roadmap_nodes.id", ondelete="SET NULL"), nullable=True
    )
    match_type: Mapped[str] = mapped_column(String(20), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    action: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
