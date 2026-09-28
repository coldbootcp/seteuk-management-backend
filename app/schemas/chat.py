import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.conversation import ChatMode


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    # 화면이 일반 잡담과 진단+상담 대화를 구분해 목록에서 걸러낼 수 있도록 노출한다.
    # 컬럼 자체는 이미 있었는데(Conversation.purpose) 응답에 빠져 있었다.
    purpose: str
    # default(상담 고정 제목) / auto(대화 주제로 지은 제목) / user(학생이 직접 고침)
    title_source: str | None = None
    created_at: datetime
    updated_at: datetime


class ConversationUpdate(BaseModel):
    """학생이 대화 제목을 직접 고칠 때. 앞뒤 공백을 걷어낸 뒤 비어 있으면 거부한다."""

    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    mode: str
    # 수정 모드에서 이 답변이 실제로 바꾼 것들 — 클라이언트가 "무엇이 기록됐는지"를
    # 대화 아래에 되짚어 보여줄 수 있게 한다.
    applied_actions: list[Any] | None
    created_at: datetime


class MessageCreate(BaseModel):
    content: str = Field(min_length=1)
    mode: ChatMode = ChatMode.NORMAL
