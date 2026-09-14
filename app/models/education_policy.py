"""입학 연도별 교육과정·대입 제도 기준.

대학별 모집요강과 달리, 이 데이터는 학생이 고등학교에 입학한 해를 기준으로
결정되는 공용 규칙이다. 정책 원문과 서비스 해석을 분리해 보관한다. 따라서
특정 학생의 성적이나 진단 데이터와 섞이지 않고, 원문이 개정되어도 과거에 어떤
기준을 적용했는지 추적할 수 있다.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class EducationPolicy(Base):
    """한 입학 연도 구간에 적용되는 고교 교육 제도 기준."""

    __tablename__ = "education_policies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    freshman_year_start: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    freshman_year_end: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    curriculum_name: Mapped[str] = mapped_column(String(160), nullable=False)
    rank_grade_scale: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    # 과목 체계·학생부 기재·수능처럼 한 문장으로 축약하면 의미가 달라지는 기준을
    # 구조화해 둔다. 화면은 이 값을 "공식 기준"으로 표시하고, 임의 계산값으로
    # 바꾸지 않는다.
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_label: Mapped[str] = mapped_column(String(200), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_published_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AdmissionPolicyRule(Base):
    """모집연도·지원 규칙처럼 학생부 등급과 별개인 대입 공통 기준.

    모든 대학에 동일한 결론을 낼 수 없는 규칙은 ``decision_scope``을
    ``track_specific``으로 저장한다. 이를 통해 "졸업생이면 무조건 가능" 같은
    잘못된 단정을 화면이나 챗봇이 만들지 않게 한다.
    """

    __tablename__ = "admission_policy_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("education_policies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    admission_year_start: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    admission_year_end: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    decision_scope: Mapped[str] = mapped_column(String(30), nullable=False, default="common")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    action_required: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_label: Mapped[str] = mapped_column(String(200), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_published_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
