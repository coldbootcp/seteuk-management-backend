import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class ReviewAlignment(StrEnum):
    ALIGNED = "aligned"
    PARTIAL = "partial"
    SEPARATE = "separate"


class ActivityReview(Base):
    """활동 하나에 대한 질적 검토.

    정합 판정(`reconciliation_logs`)과 다른 것을 답한다. 정합은 "이 활동이 로드맵
    마디를 충족했는가"를 기계적으로 채점하고, 리뷰는 "무엇이 근거로 남았고, 무엇이
    비었고, 다음에 무엇을 하면 되는가"를 말한다. 앞의 것은 진척을 옮기고 뒤의 것은
    학생에게 다음 한 걸음을 준다.

    덮어쓰지 않고 쌓는다 — 활동을 고친 뒤 다시 검토하면 이전 판단도 남아 있어야
    무엇이 달라졌는지 볼 수 있다.
    """

    __tablename__ = "activity_reviews"
    __table_args__ = (Index("ix_activity_reviews_activity_created", "activity_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    activity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("activities.id", ondelete="CASCADE"), nullable=False
    )
    roadmap_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roadmap_nodes.id", ondelete="SET NULL"), nullable=True
    )
    alignment: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 이 활동에서 실제로 근거로 쓸 수 있는 것들.
    evidence: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # 아직 비어 있는 것. 없으면 빈 배열이고 억지로 채우지 않는다.
    gaps: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    next_steps: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="deepseek")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
