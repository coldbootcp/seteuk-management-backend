import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Date, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class CalendarEventType(StrEnum):
    EXAM = "시험"
    ASSESSMENT = "수행평가"
    OTHER = "기타"


class CalendarEvent(Base):
    """시험·수행평가 기간처럼 특정 날짜 구간에 걸친 일정 하나.

    성적·활동 등 6개 탭은 "이미 일어난 일"을 담고 생기부에서 파싱될 수 있지만,
    이건 "앞으로 있을 일"을 학생이 직접 적어 두는 용도라 source_upload_id가
    없다."""

    __tablename__ = "calendar_events"
    __table_args__ = (Index("ix_calendar_events_user_start", "user_id", "start_date"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # 시험 기간은 보통 과목을 아우르고 수행평가는 과목 하나에 매이는 경우가
    # 많아 선택 항목으로 둔다.
    subject: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    memo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
