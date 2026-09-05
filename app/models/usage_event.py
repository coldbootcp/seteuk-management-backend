import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class UsageAction(StrEnum):
    SETEUK_UPLOAD = "seteuk_upload"
    DIAGNOSIS = "diagnosis"
    ROADMAP = "roadmap"
    RECOMMENDATION = "recommendation"
    CHAT_MESSAGE = "chat_message"


class UsageEvent(Base):
    """비용이 드는 LLM 작업 1회. 인메모리 카운터와 달리 워커가 여러 개여도, 프로세스가
    재시작돼도 정확하므로 요금 남용 방지에는 이쪽이 맞다."""

    __tablename__ = "usage_events"
    __table_args__ = (
        Index("ix_usage_events_user_action_created", "user_id", "action", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
