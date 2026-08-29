import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Identity data, not an "opinion" that evolves — unlike student_interests, no history.
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Current factual status, not a subjective answer — kept separate from
    # student_interests. No auto-advance-by-calendar logic yet (deferred).
    current_grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_semester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kakao_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
