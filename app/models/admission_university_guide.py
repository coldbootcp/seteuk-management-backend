"""대학 단위 대입특징·입시가이드 원문을 구조화한 공개 기준 데이터."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AdmissionUniversityGuide(Base):
    """어디가가 학년도별로 제공하는 대학 공통 대입특징과 입시가이드.

    전형별 모집요강을 대체하지 않는다. 수시·정시의 큰 변화, 전형요소, 반영 방법
    등 대학 단위 안내를 표와 문단의 원래 구조에 가깝게 저장해, 화면이 임의의
    '요약'으로 사실을 바꾸지 않도록 한다.
    """

    __tablename__ = "admission_university_guides"
    __table_args__ = (
        UniqueConstraint(
            "university_id",
            "source_admission_year",
            name="uq_admission_university_guide_year",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    university_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("universities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_admission_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # 각 섹션은 title, paragraphs, tables(rows) 구조다. 표 내부 병합은 이미
    # 행렬로 펼쳐 저장하므로, 화면은 출처 원문을 왜곡하지 않고 표시할 수 있다.
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
