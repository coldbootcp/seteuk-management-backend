import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Float, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class UploadStatus(StrEnum):
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class SeteukUpload(Base):
    __tablename__ = "seteuk_uploads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=UploadStatus.PROCESSING.value
    )
    # Kept for forward compatibility with API_SPEC.md's data model; the parser
    # does not compute a confidence score (see docs/PARSER_SPEC.md), so this
    # stays null until a future phase implements scoring.
    parsing_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 업로드 원본. 예전에는 "PDF 원본은 저장하지 않는다"가 방침이었지만 통합 결정
    # P-1에서 보관하기로 뒤집었다. 진단·챗봇 컨텍스트에는 절대 싣지 않는다 —
    # 파싱 결과(raw_result)만 그 자리에 들어간다.
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    raw_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
