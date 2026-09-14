"""전형별 자기소개·에세이 문항의 공식 원문과 제한값."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AdmissionWritingRequirement(Base):
    __tablename__ = "admission_writing_requirements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    track_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admission_tracks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 지원 대상 연도와 원문이 실제로 확인된 연도는 다를 수 있다. 과거 자료를
    # 참고로 보여줄 때 둘을 섞지 않기 위해 원문 연도를 별도로 보관한다.
    source_admission_year: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    prompt_label: Mapped[str] = mapped_column(String(160), nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    min_characters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_characters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    character_unit: Mapped[str] = mapped_column(String(30), nullable=False, default="자")
    submission_method: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_status: Mapped[str] = mapped_column(String(20), nullable=False, default="plan")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
