"""대입정보포털에서 수집한 대학 단위 입시 통계 스냅샷.

전형·모집단위별 결과와 달리, 이 테이블은 대학 전체의 최근 모집/지원 인원,
경쟁률, 취업률, 전형유형 분포를 한 원천 응답 단위로 보관한다. 원천이 제공하는
과거 연도 계열도 JSON으로 그대로 구조화해, 화면에서 어느 학년도 수치인지
명확히 붙일 수 있게 한다.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AdmissionUniversitySnapshot(Base):
    __tablename__ = "admission_university_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "university_id",
            "source_admission_year",
            name="uq_admission_university_snapshot_year",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    university_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("universities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 화면을 열 때 선택한 모집연도. 응답 안에는 이 해를 기준으로 한 과거 통계
    # 계열이 함께 들어 있으므로, 개별 항목의 syr도 payload에 보존한다.
    source_admission_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
