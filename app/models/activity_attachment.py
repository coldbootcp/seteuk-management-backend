import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class ActivityAttachment(Base):
    """활동에 딸린 파일(수행평가 안내문, 보고서 등).

    통합 결정 P-1에 따라 파일 본문을 PostgreSQL에 그대로 담는다. 원래 프론트엔드는
    R2에 올리고 키만 들고 있었지만, Workers를 버리면서 저장소도 하나로 모았다.
    본문(`content`)은 절대 LLM 컨텍스트에 싣지 않는다 — 필요한 것은 `extracted_text`다.
    """

    __tablename__ = "activity_attachments"
    __table_args__ = (Index("ix_activity_attachments_activity", "activity_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    activity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("activities.id", ondelete="CASCADE"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
