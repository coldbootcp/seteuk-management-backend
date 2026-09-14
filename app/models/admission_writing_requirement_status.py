"""전형별 자기소개·에세이 요구 여부의 검증 상태.

문항 행이 없다는 사실만으로는 '자기소개서 미요구'라고 말할 수 없다. 원문을
읽었는지, 어떤 학년도 자료인지, 그리고 아직 판독하지 못했는지를 전형과 분리해
보관한다.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AdmissionWritingRequirementStatus(Base):
    __tablename__ = "admission_writing_requirement_statuses"
    __table_args__ = (Index("ix_admission_writing_requirement_statuses_track_id", "track_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    track_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admission_tracks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # required | not_required | unverified
    requirement_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unverified"
    )
    source_admission_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    verification_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
