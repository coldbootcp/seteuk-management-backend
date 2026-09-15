import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AuthRateLimitEvent(Base):
    """로그인 전 엔드포인트(가입/로그인/비밀번호 재설정 요청 등) 남용 방지용
    시도 1건. UsageEvent는 user_id FK라 로그인하지 않은 상태의 시도(존재하지
    않는 이메일로의 무차별 대입 등)를 셀 수 없어, IP·이메일 같은 임의 문자열
    키로 세는 별도 테이블을 둔다. 짧은 윈도우(분 단위)라 24시간 슬라이딩
    윈도우인 UsageEvent와도 목적이 다르다."""

    __tablename__ = "auth_rate_limit_events"
    __table_args__ = (
        Index("ix_auth_rate_limit_key_action_created", "key", "action", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # "ip:1.2.3.4" 또는 "email:user@example.com" 형태.
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
