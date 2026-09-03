import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AcademicPerformance(Base):
    __tablename__ = "academic_performance"

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
    semester: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    subject: Mapped[str] = mapped_column(String(100), nullable=False)
    units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    achievement_grade: Mapped[str | None] = mapped_column(String(5), nullable=True)
    student_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    subject_average: Mapped[float | None] = mapped_column(Float, nullable=True)
    std_deviation: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 이 과목이 어느 로드맵 노드를 위한 수강인지(D-3). 생기부 파싱으로 들어온
    # 행은 비어 있고, 학생이 로드맵에서 과목을 고를 때 채워진다.
    roadmap_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roadmap_nodes.id", ondelete="SET NULL"), nullable=True
    )
    rank: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
