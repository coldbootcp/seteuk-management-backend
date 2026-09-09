import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class Award(Base):
    __tablename__ = "awards"

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
    # 생기부 수상 표에는 학년 열이 따로 없다. 대신 "참가대상"이 "3학년(216명)"처럼
    # 학년을 담고 있고, 수상연월일이 학기를 알려 준다 — 둘을 합쳐 파싱 시점에
    # 채운다. 근거가 부족한 행은 비워 두고, 비어 있음을 그대로 드러낸다.
    grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    semester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 학년을 어디서 읽었는지 남긴다(참가대상 원문). 잘못 읽었을 때 되짚기 위한 것.
    participants: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    rank: Mapped[str | None] = mapped_column(String(100), nullable=True)
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
    raw_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
