"""Phase 3 — 챗봇.

응답은 SSE로 흘려보낸다. StreamingResponse의 본문은 요청 의존성이 정리된 뒤에도
계속 실행되므로, 스트리밍 제너레이터는 라우터가 쥔 세션을 쓰지 않고 자체 세션을
연다(비동기 job과 같은 패턴).

'수정' 모드는 사용자가 토글을 켠 것 자체를 동의로 보고 도구를 즉시 실행하되,
tools.py에 삭제 도구를 두지 않아 대화만으로 기록이 사라지는 일은 없다.
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConversationNotFoundError, LLMUnavailableError
from app.db.session import AsyncSessionLocal
from app.models.conversation import ChatMode, Conversation, Message, MessageRole
from app.models.user import User
from app.services.chat.context import build_context
from app.services.chat.prompts import build_system_prompt
from app.services.chat.tools import TOOL_SPECS, execute_tool
from app.services.llm import stream_chat

logger = logging.getLogger(__name__)

# 대화에 실어 보내는 직전 메시지 수. 그 앞의 맥락은 <학생_데이터>가 대신한다.
HISTORY_LIMIT = 20
# 도구 호출 → 결과 → 다시 호출을 몇 번까지 허용할지. 무한 루프 방지용.
MAX_TOOL_ROUNDS = 4
TITLE_LIMIT = 60


async def create_conversation(db: AsyncSession, user_id: uuid.UUID) -> Conversation:
    conversation = Conversation(user_id=user_id)
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def get_conversation(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )
    if conversation is None:
        raise ConversationNotFoundError("대화를 찾을 수 없습니다")
    return conversation


async def delete_conversation(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> None:
    conversation = await get_conversation(db, user_id, conversation_id)
    await db.delete(conversation)
    await db.commit()


async def list_messages(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> list[Message]:
    await get_conversation(db, user_id, conversation_id)
    rows = await db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    return list(rows)


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _merge_tool_call_deltas(
    accumulator: dict[int, dict[str, Any]], deltas: list[Any]
) -> None:
    """OpenAI 호환 스트림은 도구 호출을 index별 조각으로 흘려보낸다 — 이름은 보통
    첫 조각에만, 인자는 여러 조각에 걸쳐 나뉘어 온다."""
    for delta in deltas:
        slot = accumulator.setdefault(delta.index, {"id": "", "name": "", "arguments": ""})
        if delta.id:
            slot["id"] = delta.id
        if delta.function is not None:
            if delta.function.name:
                slot["name"] = delta.function.name
            if delta.function.arguments:
                slot["arguments"] += delta.function.arguments


async def stream_reply(
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    content: str,
    mode: ChatMode,
) -> AsyncIterator[str]:
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if user is None:
            yield _sse("error", {"error_code": "USER_NOT_FOUND", "message": "사용자 없음"})
            return

        conversation = await get_conversation(db, user_id, conversation_id)

        # 스트림이 도중에 끊겨도 학생이 한 말은 남아야 하므로 먼저 저장한다.
        user_message = Message(
            conversation_id=conversation_id,
            role=MessageRole.USER.value,
            content=content,
            mode=mode.value,
        )
        db.add(user_message)
        if conversation.title is None:
            conversation.title = content[:TITLE_LIMIT]
        await db.commit()

        history = await db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.id != user_message.id)
            .order_by(Message.created_at.desc())
            .limit(HISTORY_LIMIT)
        )
        context = await build_context(db, user)

        llm_messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": build_system_prompt(
                    json.dumps(context, ensure_ascii=False), edit_mode=mode == ChatMode.EDIT
                ),
            }
        ]
        llm_messages.extend(
            {"role": m.role, "content": m.content} for m in reversed(list(history))
        )
        llm_messages.append({"role": "user", "content": content})

        tools = TOOL_SPECS if mode == ChatMode.EDIT else None
        applied_actions: list[dict[str, Any]] = []
        answer_parts: list[str] = []

        try:
            for _ in range(MAX_TOOL_ROUNDS):
                round_text: list[str] = []
                tool_calls: dict[int, dict[str, Any]] = {}

                async for chunk in stream_chat(llm_messages, tools):
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta.content:
                        if not round_text and answer_parts:
                            # 도구 실행 전에 흘린 말과 실행 후의 답변이 그대로 붙어
                            # 한 문장처럼 보이지 않도록 문단을 나눈다.
                            answer_parts.append("\n\n")
                            yield _sse("token", {"delta": "\n\n"})
                        round_text.append(delta.content)
                        yield _sse("token", {"delta": delta.content})
                    if delta.tool_calls:
                        _merge_tool_call_deltas(tool_calls, delta.tool_calls)

                answer_parts.extend(round_text)
                if not tool_calls:
                    break

                llm_messages.append(
                    {
                        "role": "assistant",
                        "content": "".join(round_text) or None,
                        "tool_calls": [
                            {
                                "id": call["id"],
                                "type": "function",
                                "function": {
                                    "name": call["name"],
                                    "arguments": call["arguments"] or "{}",
                                },
                            }
                            for call in tool_calls.values()
                        ],
                    }
                )

                for call in tool_calls.values():
                    try:
                        arguments = json.loads(call["arguments"] or "{}")
                    except json.JSONDecodeError:
                        arguments = {}
                        result: dict[str, Any] = {"error": "도구 인자를 해석하지 못했습니다"}
                    else:
                        result = await execute_tool(db, user, call["name"], arguments)

                    action = {"tool": call["name"], "arguments": arguments, "result": result}
                    applied_actions.append(action)
                    yield _sse("action", action)
                    llm_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        }
                    )
            else:
                logger.warning(
                    "chat tool loop hit the round limit: conversation_id=%s", conversation_id
                )
        except LLMUnavailableError as exc:
            yield _sse("error", {"error_code": "LLM_UNAVAILABLE", "message": exc.message})
            return
        except Exception:
            logger.exception("chat stream failed: conversation_id=%s", conversation_id)
            yield _sse(
                "error",
                {"error_code": "LLM_UNAVAILABLE", "message": "잠시 후 다시 시도해주세요"},
            )
            return

        assistant_message = Message(
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT.value,
            content="".join(answer_parts),
            mode=mode.value,
            applied_actions=applied_actions or None,
        )
        db.add(assistant_message)
        await db.commit()
        await db.refresh(assistant_message)

        yield _sse(
            "done",
            {"message_id": str(assistant_message.id), "applied_actions": applied_actions},
        )
