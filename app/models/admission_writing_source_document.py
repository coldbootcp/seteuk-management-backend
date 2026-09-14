"""대학별 모집요강 원문의 최소 검증 메타데이터.

원문 PDF 전문은 재배포하거나 저장하지 않는다. 다시 내려받을 수 있는 공식 URL과
판독 결과만 저장해 전형별 검증 작업을 재사용한다.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AdmissionWritingSourceDocument(Base):
    __tablename__ = "admission_writing_source_documents"
    __table_args__ = (
        UniqueConstraint(
            "university_id", "source_admission_year", name="uq_writing_source_university_year"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    university_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("universities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_admission_year: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    # inspected | unreadable | unavailable
    inspection_status: Mapped[str] = mapped_column(String(20), nullable=False)
    has_writing_marker: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    marker_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inspection_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    inspected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
