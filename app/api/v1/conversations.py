import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.rate_limit import enforce_daily_limit
from app.db.session import get_db
from app.models.conversation import Conversation
from app.models.usage_event import UsageAction
from app.models.user import User
from app.schemas.chat import ConversationRead, MessageCreate, MessageRead
from app.schemas.records import ListResponse
from app.services import chat_service, record_service

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationFilters(BaseModel):
    limit: int = Field(default=30, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


@router.post("", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationRead:
    conversation = await chat_service.create_conversation(db, user.id)
    return ConversationRead.model_validate(conversation)


@router.get("", response_model=ListResponse[ConversationRead])
async def list_conversations(
    filters: Annotated[ConversationFilters, Query()],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ListResponse[ConversationRead]:
    rows, total = await record_service.list_records(
        db,
        Conversation,
        user.id,
        filters={},
        order_by=[Conversation.updated_at.desc()],
        limit=filters.limit,
        offset=filters.offset,
    )
    return ListResponse[ConversationRead](
        items=[ConversationRead.model_validate(row) for row in rows], total=total
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await chat_service.delete_conversation(db, user.id, conversation_id)


@router.get("/{conversation_id}/messages", response_model=list[MessageRead])
async def list_messages(
    conversation_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[MessageRead]:
    messages = await chat_service.list_messages(db, user.id, conversation_id)
    return [MessageRead.model_validate(m) for m in messages]


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: uuid.UUID,
    data: MessageCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """SSE 스트리밍 응답. 소유권만 여기서 확인하고, 실제 생성은 자체 세션을 여는
    제너레이터가 맡는다 — 스트리밍 본문은 요청 의존성보다 오래 살기 때문이다."""
    await chat_service.get_conversation(db, user.id, conversation_id)
    await enforce_daily_limit(db, user.id, UsageAction.CHAT_MESSAGE)
    return StreamingResponse(
        chat_service.stream_reply(user.id, conversation_id, data.content, data.mode),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
