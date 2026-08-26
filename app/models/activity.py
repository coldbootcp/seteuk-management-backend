import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class ActivityCategory(StrEnum):
    SUBJECT_SPECIALTY = "과목세부특기사항"
    AUTONOMOUS = "자율활동"
    CLUB = "동아리활동"
    CAREER = "진로활동"
    BEHAVIOR = "행동특성및종합의견"


class ActivityType(StrEnum):
    REPORT = "report"
    PRESENTATION = "presentation"
    EXPERIMENT = "experiment"
    PROJECT = "project"
    READING_LINKED = "reading_linked"
    OTHER = "other"


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # Null means this row was entered some other way (e.g. manual edit in a future
    # tab-management API), not parsed from a 생기부 upload — re-uploading only
    # replaces rows that trace back to a previous upload, never these.
    source_upload_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("seteuk_uploads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    semester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    activity_category: Mapped[str] = mapped_column(String(50), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(100), nullable=True)
    activity_name: Mapped[str] = mapped_column(String(255), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str] = mapped_column(String, nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_block: Mapped[str | None] = mapped_column(String, nullable=True)
    # Not computed by the parser yet — see docs/PARSER_SPEC.md; always null for now.
    parsing_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
