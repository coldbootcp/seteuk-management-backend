import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class StudentInterest(Base):
    """The user's own, timestamped, subjective answers — completely separate from
    생기부-sourced data. field_key is not a fixed enum: onboarding writes a known set
    (career_goal, target_department, ...), and a future chatbot can write freeform
    keys extracted from conversation. A write to an existing (user_id, field_key)
    within 7 days of its answered_at overwrites value in place and keeps answered_at,
    so history only grows on genuine shifts — see student_interest_service.py."""

    __tablename__ = "student_interests"
    __table_args__ = (
        Index(
            "ix_student_interests_user_field_answered",
            "user_id",
            "field_key",
            "answered_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    field_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    value: Mapped[dict | list | str] = mapped_column(JSONB, nullable=False)
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
