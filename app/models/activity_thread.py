import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class ActivityThreadStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    CONCLUDED = "concluded"


class ActivityThread(Base):
    """활동 주제 — 진로 사슬의 단위.

    이전에는 계보가 `activities.parent_activity_id` 하나뿐이라 활동이 1:1로만 이어졌고,
    그래서 사슬이 '쌍의 나열'이지 '하나의 주제가 흐르는 것'이 아니었다. 주제를 1급
    객체로 올려 여러 활동이 한 주제에 시간순으로 매달리게 하면, 학생이 동시에 굴리는
    여러 갈래(예: 로봇 / 데이터 분석)가 각자의 흐름을 갖는다.

    `parent_activity_id`는 그대로 남는다 — 주제 안에서 '이 활동이 어떤 활동을 직접
    이어받았는지'라는 더 세밀한 질문에 답하기 때문이다. 둘은 다른 축이다.
    """

    __tablename__ = "activity_threads"
    __table_args__ = (Index("ix_activity_threads_user_status", "user_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ActivityThreadStatus.ACTIVE.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
