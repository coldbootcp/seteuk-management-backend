import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class Recommendation(Base):
    """기능2 — 특정 과거 활동에서 뻗어 나온 후속 탐구 제안 묶음. 한 번의 요청이
    여러 선택지를 만들어내므로 options(JSONB 배열)로 통째로 보관하고, 사용자가
    고른 선택지는 plan_items.source_recommendation_id로 이어진다."""

    __tablename__ = "recommendations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # 활동이 삭제돼도 추천 이력 자체는 남긴다.
    source_activity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("activities.id", ondelete="SET NULL"), nullable=True
    )
    desired_activity_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    options: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
