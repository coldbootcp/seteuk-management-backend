import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatMode(StrEnum):
    """'수정' 토글. normal은 개인화된 세특 메모리를 근거로 답만 하고,
    edit은 도구 호출로 실제 기록/메모리/진단을 바꿀 수 있다."""

    NORMAL = "normal"
    EDIT = "edit"


class ConversationPurpose(StrEnum):
    """일반 잡담과 진단+상담 관문을 통과시키는 상담 대화를 구분한다. 관문
    의존성(require_consultation_satisfied)이 general 대화에는 걸리지만 상담
    대화 자체는 관문을 통과하기 위한 경로라 걸리지 않는다."""

    GENERAL = "general"
    INITIAL_CONSULTATION = "initial_consultation"
    SEMESTER_REVIEW_CONSULTATION = "semester_review_consultation"
    GRADUATE_FIT_CONSULTATION = "graduate_fit_consultation"


class TitleSource(StrEnum):
    """대화 제목이 어디서 왔는가. 학생이 직접 고친 제목(user)은 어떤 자동 경로도
    덮어쓰지 않는다. default는 상담처럼 목적이 정해진 대화의 고정 제목, auto는 대화
    내용에서 주제를 읽어 지은 제목이다."""

    DEFAULT = "default"
    AUTO = "auto"
    USER = "user"


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title_source: Mapped[str | None] = mapped_column(String(10), nullable=True)
    purpose: Mapped[str] = mapped_column(
        String(40), nullable=False, default=ConversationPurpose.GENERAL.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default=ChatMode.NORMAL.value)
    # 수정 모드에서 실제로 실행된 도구 호출 기록(도구명 + 인자 + 결과 요약).
    # 어떤 변경이 이 답변에서 비롯됐는지 사용자에게 되짚어 보여주기 위해 남긴다.
    applied_actions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
