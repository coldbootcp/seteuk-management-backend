import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class LLMUsageEvent(Base):
    """AI 호출 한 번의 토큰 사용량. 학생 1인당·기능별 비용을 계산하려고 남긴다.

    내용(프롬프트·답변)은 저장하지 않는다 — 숫자만 남긴다. 계정을 지워도 비용 통계는
    남도록 user_id는 SET NULL이다. path는 그 호출을 일으킨 API 경로(예:
    /api/v1/consultation/sessions/:id/messages)라 기능 구분에 쓴다.
    """

    __tablename__ = "llm_usage_events"
    __table_args__ = (Index("ix_llm_usage_events_created_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    path: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    # json(구조화 호출) 또는 stream(챗봇·상담).
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 답하기 전에 쓴 "생각" 토큰. 출력 요금으로 과금된다.
    thinking_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
