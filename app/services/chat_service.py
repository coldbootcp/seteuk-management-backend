"""Phase 3 — 챗봇.

응답은 SSE로 흘려보낸다. StreamingResponse의 본문은 요청 의존성이 정리된 뒤에도
계속 실행되므로, 스트리밍 제너레이터는 라우터가 쥔 세션을 쓰지 않고 자체 세션을
연다(비동기 job과 같은 패턴).

'수정' 모드는 사용자가 토글을 켠 것 자체를 동의로 보고 도구를 즉시 실행하되,
tools.py에 삭제 도구를 두지 않아 대화만으로 기록이 사라지는 일은 없다.
"""

import asyncio
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConsultationSessionNotFoundError,
    ConversationNotFoundError,
    LLMUnavailableError,
)
from app.db.session import AsyncSessionLocal
from app.models.consultation import ConsultationKind, ConsultationStatus
from app.models.conversation import ChatMode, Conversation, Message, MessageRole
from app.models.user import User
from app.services import consultation_service
from app.services.chat.consultation_prompts import build_consultation_system_prompt
from app.services.chat.consultation_tools import (
    GRADUATE_FIT_TOOL_SPECS,
    execute_consultation_tool,
    execute_graduate_fit_tool,
)
from app.services.chat.consultation_tools import (
    TOOL_SPECS as CONSULTATION_TOOL_SPECS,
)
from app.services.chat.context import build_context, prepare_context_for_chat
from app.services.chat.prompts import build_system_prompt
from app.services.chat.tools import TOOL_SPECS, execute_tool
from app.services.llm import call_structured, stream_chat

logger = logging.getLogger(__name__)

# 대화에 실어 보내는 직전 메시지 수. 그 앞의 맥락은 <학생_데이터>가 대신한다.
HISTORY_LIMIT = 20
# 도구 호출 → 결과 → 다시 호출을 몇 번까지 허용할지. 무한 루프 방지용.
MAX_TOOL_ROUNDS = 4
TITLE_LIMIT = 60

_GRADE_PERIOD = re.compile(r"([1-3])\s*학년(?:\s*([1-2])\s*학기)?")
_SIX_SEMESTER_LANGUAGE = re.compile(
    r"(?:앞으로\s*)?6(?:개)?\s*학기(?:의\s*(?:탐구\s*)?(?:여정|흐름|계획|구성))?"
)
_UNVERIFIED_RECORD_ABSENCE = re.compile(
    r"(?:학생부|생기부|활동|성적|독서|수상|봉사|저장된\s*(?:과거\s*)?기록).{0,80}"
    r"(?:전혀\s*)?(?:기록되지\s*않|하나도\s*없|없(?:습니다|어요|다)|확인되지\s*않)",
    re.IGNORECASE,
)
_RECORD_COVERAGE_UNAVAILABLE = {
    "not_uploaded",
    "processing",
    "failed",
    "awaiting_import",
}
_DIRECTION_REASK = re.compile(
    r"(?:진로|분야).{0,35}(?:정하게\s*된\s*계기|선택한\s*이유|처음\s*정한\s*계기)"
    r"|(?:왜|어떤\s*계기).{0,35}(?:진로|분야)"
    r"|(?:어느|어떤)\s*세부\s*(?:영역|분야).{0,25}(?:관심|끌리)",
    re.IGNORECASE,
)
_METHOD_PREFERENCE_REASK = re.compile(
    r"(?:아니면\s*)?(?:시뮬레이션|실험|발표|보고서|이론|개념\s*정리).{0,90}"
    r"(?:선호하(?:시)?는|원하(?:시)?는|방식(?:을|이)|형식(?:을|이)).{0,90}"
    r"(?:알려|말해|답해|선택해).{0,90}(?:\.|\?|$)",
    re.IGNORECASE,
)
_UNVERIFIED_SPECIFIC_COURSE = re.compile(
    r"(?:국어|영어|수학|물리(?:학)?|화학|생명과학|지구과학|통합과학|정보)\s*[ⅠⅡIVX0-9]+"
)
_INTERNAL_DRAFT_RETRY = re.compile(
    r"(?:설계|계획)\s*(?:저장\s*)?형식이\s*잘못되어\s*다시\s*시도하겠습니다\.?\s*"
)
_DRAFT_SAVED_CLAIM = re.compile(r"계획이\s*(?:잘\s*)?저장되었습니다")
_PREMATURE_DRAFT_CONFIRMATION = re.compile(
    r"계획\s*초안(?:을|이)[^.!?]{0,80}(?:확정|저장)[^.!?]{0,80}[.!?]\s*"
)
# 실제로 저장된 계획 제목을 근거로 하지 않고, 모델이 임의의 주제가 이미 계획에
# 들어 있는 것처럼 단정한 응답을 마지막에 차단한다. 새 주제를 "제안합니다"라고
# 말하는 것은 허용하되, "제안되어 있습니다"처럼 기존 사실로 말하는 문장만 막는다.
_UNVERIFIED_PLAN_CLAIM = re.compile(
    r"(?:제안되어|계획되어|정해져|등록되어|포함되어|반영되어)\s*(?:있(?:습니다|어요|다)|있는)"
    r"|이미.{0,50}(?:계획|제안|로드맵).{0,50}(?:있(?:습니다|어요|다)|되어)",
    re.IGNORECASE,
)


def _period_index(grade: int, semester: int) -> int:
    return (grade - 1) * 2 + (semester - 1)


def filter_consultation_output_for_period(
    text: str,
    *,
    target_grade: int,
    target_semester: int,
    school_record_status: str = "imported",
    has_declared_direction: bool = False,
    has_current_course_data: bool = True,
    confirmed_plan_titles: list[str] | None = None,
) -> str:
    """현재보다 앞선 학기를 새 계획처럼 보이는 상담 문장에서 제거한다.

    DeepSeek가 프롬프트의 '과거는 회고' 규칙을 무시한 실제 응답이 있었기 때문에,
    학생에게 보내기 직전에 다시 검사한다. 한 줄에 과거 학기가 들어 있으면 통째로
    버린다. 과거·현재를 한 줄에 섞어 버린 모델 문장을 보존하는 것보다, 현재와 미래
    계획만 남기는 편이 안전하다.
    """
    current = _period_index(target_grade, target_semester)
    kept: list[str] = []
    for line in text.splitlines():
        periods = _GRADE_PERIOD.findall(line)
        mentions_past = any(
            _period_index(int(grade), int(semester or "1")) < current
            for grade, semester in periods
        )
        if not mentions_past:
            kept.append(line)

    filtered = "\n".join(kept)
    if current > 0:
        filtered = _SIX_SEMESTER_LANGUAGE.sub("현재 학기부터 남은 학기", filtered)

    # 이미 저장된 진로·학과·관심 축을 모델이 다시 질문한 실제 응답을 막는다.
    # 이 필터는 방향이 전혀 없는 학생의 필요한 탐색 질문은 지우지 않는다.
    if has_declared_direction:
        filtered = "\n".join(
            line for line in filtered.splitlines() if not _DIRECTION_REASK.search(line)
        )

    # 결과물·수행 방식은 학교에 실제 기회가 생긴 뒤 학생이 정할 사항이다. 모델이
    # 주제 제안 직후 이를 사전 설문처럼 되묻는 문장을 제거한다.
    filtered = _METHOD_PREFERENCE_REASK.sub("", filtered)

    # 수강 과목이 아직 등록되지 않았는데 특정 교과를 실제 수강 중인 것처럼
    # 연결한 실제 응답을 막는다. 주제 설명은 보존하고, 확인되지 않은 과목명만
    # 중립적인 표현으로 바꾼다.
    if not has_current_course_data:
        filtered = _UNVERIFIED_SPECIFIC_COURSE.sub("실제 수강 중인 관련 과목", filtered)

    # 초안 도구의 재시도는 모델 내부 처리일 뿐 학생이 볼 오류가 아니다. 또한
    # 상담 완료 전에는 계획이 확정·저장된 것이 아니므로 표현을 바로잡는다.
    filtered = _INTERNAL_DRAFT_RETRY.sub("", filtered)
    filtered = _DRAFT_SAVED_CLAIM.sub("이번 학기 계획 초안을 정리했습니다", filtered)
    filtered = _PREMATURE_DRAFT_CONFIRMATION.sub("", filtered)

    # 최초 상담에는 확정된 계획이 없으며, 재평가 상담에서도 실제 저장된 제목에
    # 없는 주제를 기존 계획이라고 부르면 안 된다. 프롬프트만으로는 이 규칙을
    # 지키지 않은 실제 모델 응답이 있었으므로, 해당 문장은 학생에게 보내지 않는다.
    # 제목이 있는 문장은 보존해 기존 계획의 정상적인 회고는 가능하게 한다.
    plan_titles = confirmed_plan_titles or []
    filtered = "\n".join(
        line
        for line in filtered.splitlines()
        if not _UNVERIFIED_PLAN_CLAIM.search(line)
        or any(title and title in line for title in plan_titles)
    )

    # 프롬프트만으로는 '활동 배열이 비었다'는 이유로 과거 활동이 없다고 단정하는
    # 실제 DeepSeek 응답을 막지 못했다. 학생부가 아직 반영되지 않았으면 문장 자체를
    # 제거하고, 확인 범위를 명시한 사실 문장으로 한 번만 바꾼다.
    if school_record_status in _RECORD_COVERAGE_UNAVAILABLE:
        lines = filtered.splitlines()
        kept_lines = [line for line in lines if not _UNVERIFIED_RECORD_ABSENCE.search(line)]
        if len(kept_lines) != len(lines):
            filtered = (
                "학생부가 아직 반영되지 않아 이전 활동의 존재 여부는 확인할 수 없습니다. "
                "현재 저장된 기록이 비어 있다는 사실만으로 활동이 없었다고 판단하지 않습니다.\n\n"
                + "\n".join(kept_lines)
            )

    return re.sub(r"\n{3,}", "\n\n", filtered).strip()


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


async def _touch(db: AsyncSession, conversation_id: uuid.UUID) -> None:
    """대화 목록은 updated_at 내림차순으로 보여준다. 그런데 메시지를 추가해도
    conversations 행 자체는 UPDATE되지 않아 onupdate가 걸리지 않는다 — 명시적으로
    갱신하지 않으면 첫 메시지 이후로 시각이 얼어붙어, 방금 대화한 방이 목록 맨
    아래에 남는다.

    ORM 객체의 속성을 대입하지 않고 UPDATE를 직접 실행하는 이유는, commit 뒤
    만료된 인스턴스에 대입하면 예전 값을 읽으려는 지연 로드가 걸려 스트리밍
    제너레이터 안에서 MissingGreenlet으로 터지기 때문이다."""
    await db.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(updated_at=datetime.now(UTC))
    )


async def _persist_assistant_turn(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    mode: ChatMode,
    answer: str,
    applied_actions: list[dict[str, Any]],
) -> Message | None:
    """답변과 실행된 도구를 저장한다. 스트림이 도중에 끊겨도 반드시 불러야 한다 —
    도구는 이미 DB를 바꿔 놓은 뒤라, 여기서 저장하지 않으면 기록은 바뀌었는데
    무엇이 바뀌었는지 아무 데도 남지 않는다.

    아무것도 만들어지지 않았으면(내용도 도구 실행도 없음) 빈 답변을 남기지 않는다.
    """
    if not answer and not applied_actions:
        return None

    message = Message(
        conversation_id=conversation_id,
        role=MessageRole.ASSISTANT.value,
        content=answer,
        mode=mode.value,
        applied_actions=applied_actions or None,
    )
    db.add(message)
    await _touch(db, conversation_id)
    await db.commit()
    await db.refresh(message)
    return message


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

        try:
            conversation = await get_conversation(db, user_id, conversation_id)
        except ConversationNotFoundError as exc:
            # 라우터에서 확인한 뒤 스트림이 시작되기까지 사이에 지워질 수 있다.
            yield _sse("error", {"error_code": "CONVERSATION_NOT_FOUND", "message": exc.message})
            return

        # 스트림이 도중에 끊겨도 학생이 한 말은 남아야 하므로 먼저 저장한다.
        user_message = Message(
            conversation_id=conversation_id,
            role=MessageRole.USER.value,
            content=content,
            mode=mode.value,
        )
        db.add(user_message)
        if conversation.title is None:
            conversation.title = " ".join(content.split())[:TITLE_LIMIT]
        await _touch(db, conversation_id)
        await db.commit()

        history = await db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.id != user_message.id)
            .order_by(Message.created_at.desc())
            .limit(HISTORY_LIMIT)
        )
        context = await build_context(db, user)
        model_context, reference_catalog = prepare_context_for_chat(context)

        llm_messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": build_system_prompt(
                    json.dumps(model_context, ensure_ascii=False), edit_mode=mode == ChatMode.EDIT
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
        error_payload: dict[str, Any] | None = None

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
                        result = await execute_tool(
                            db, user, call["name"], arguments, reference_catalog
                        )

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
        except asyncio.CancelledError:
            # 사용자가 창을 닫거나 요청을 취소한 경우. 도구가 이미 실행돼 DB를 바꿔
            # 놓았을 수 있으므로, 취소가 저장까지 함께 끊지 않도록 shield로 감싼다.
            await asyncio.shield(
                _persist_assistant_turn(
                    db, conversation_id, mode, "".join(answer_parts), applied_actions
                )
            )
            raise
        except LLMUnavailableError as exc:
            error_payload = {"error_code": "LLM_UNAVAILABLE", "message": exc.message}
        except Exception:
            logger.exception("chat stream failed: conversation_id=%s", conversation_id)
            error_payload = {
                "error_code": "LLM_UNAVAILABLE",
                "message": "잠시 후 다시 시도해주세요",
            }

        # 실패했더라도 여기까지 흘린 답변과 실행된 도구는 반드시 남긴다.
        assistant_message = await _persist_assistant_turn(
            db, conversation_id, mode, "".join(answer_parts), applied_actions
        )

        if error_payload is not None:
            yield _sse("error", error_payload)
            return

        yield _sse(
            "done",
            {
                "message_id": str(assistant_message.id) if assistant_message else None,
                "applied_actions": applied_actions,
            },
        )


class _SuggestedReplies(BaseModel):
    """챗봇의 마지막 말에 학생이 이어서 할 만한 짧은 답변 후보."""

    replies: list[str] = []


_SUGGESTED_REPLIES_PROMPT = """너는 고등학생 진로·입시 상담 화면의 '추천 답변'을 만드는
보조 AI다. 방금 컨설턴트(assistant)가 학생에게 한 말을 보고, **학생 입장에서** 이어서
보낼 만한 짧은 답변 후보를 정확히 3개 만들어라.

[규칙]
1. 반드시 컨설턴트의 마지막 말에 자연스럽게 이어지는 답이어야 한다. 컨설턴트가
   질문했으면 그 질문에 대한 서로 다른 방향의 답을, 선택지를 제시했으면 각 선택을
   고르는 답을 만들어라. 맥락과 무관한 일반적인 문장을 지어내지 마라.
2. 학생이 실제로 눌러서 그대로 보낼 1인칭 발화체다("~해주세요", "~가 궁금해요",
   "~로 할게요" 등). 컨설턴트 말투(존댓말 설명체)로 쓰지 마라.
3. 각 12~30자로 짧게. 세 개는 서로 뚜렷이 다른 선택/방향이어야 한다.
4. 반드시 아래 JSON만 출력하라: {"replies": ["...", "...", "..."]}"""


async def _generate_suggested_replies(assistant_text: str) -> list[str]:
    """챗봇 마지막 답변에 맞춘 학생용 추천 답변 3개. 실패해도 상담 흐름을 막지
    않도록 예외를 삼키고 빈 목록을 돌려준다(화면은 칩을 안 보여줄 뿐이다)."""
    text = (assistant_text or "").strip()
    if not text:
        return []
    try:
        result = await call_structured(
            _SUGGESTED_REPLIES_PROMPT,
            json.dumps({"consultant_last_message": text}, ensure_ascii=False),
            _SuggestedReplies,
        )
    except Exception:
        logger.warning("suggested replies generation failed", exc_info=True)
        return []
    # 빈 문자열·중복 제거 후 최대 3개.
    seen: set[str] = set()
    cleaned: list[str] = []
    for r in result.replies:
        r = r.strip()
        if r and r not in seen:
            seen.add(r)
            cleaned.append(r)
    return cleaned[:3]


async def stream_consultation_opening(
    user_id: uuid.UUID,
    session_id: uuid.UUID,
) -> AsyncIterator[str]:
    """새로 열린 상담 세션의 첫 인사를 모델이 직접 짓게 한다. 학생이 빈 입력칸
    앞에서 멈추지 않도록, 진단·학생 데이터를 본 챗봇이 먼저 말을 건다. 학생 메시지
    없이 시스템 프롬프트만으로 여는 말을 만들며, 도구는 주지 않는다(첫 인사에서
    계획을 저장하거나 학과를 조회할 이유가 없다). 이미 대화가 시작된 세션이면
    중복 인사를 만들지 않고 조용히 끝낸다."""
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if user is None:
            yield _sse("error", {"error_code": "USER_NOT_FOUND", "message": "사용자 없음"})
            return
        try:
            session = await consultation_service.get_session(db, user_id, session_id)
        except ConsultationSessionNotFoundError as exc:
            yield _sse(
                "error",
                {"error_code": "CONSULTATION_SESSION_NOT_FOUND", "message": exc.message},
            )
            return

        conversation_id = session.conversation_id
        # 이미 어시스턴트 인사나 학생 발화가 있으면 첫 인사를 또 만들지 않는다.
        existing = await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )
        if existing:
            yield _sse("done", {"message_id": None, "applied_actions": []})
            return

        context = await build_context(db, user)
        roadmap_summary = await consultation_service.get_active_plan_summary(db, user)
        system_prompt = build_consultation_system_prompt(
            session.kind,
            json.dumps(context, ensure_ascii=False),
            json.dumps(roadmap_summary, ensure_ascii=False)
            if roadmap_summary is not None
            else None,
        )
        # 학생 발화 대신, 여는 말을 건네라는 지시를 준다. 이 지시문은 저장하지 않고
        # (학생에게 보이지 않아야 한다), 생성된 인사만 어시스턴트 메시지로 남긴다.
        llm_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "[시스템 안내: 지금 상담 화면이 막 열렸고 학생은 아직 아무 말도 하지 "
                    "않았습니다. 진단 결과와 학생 데이터를 근거로, 학생에게 먼저 건네는 "
                    "여는 말을 한 번 해주세요. 무엇을 근거로 보고 있는지 짧게 밝히고, "
                    "학생이 어떤 이야기부터 꺼내면 좋을지 한 가지만 자연스럽게 물어보며 "
                    "대화를 시작하세요. 도구는 호출하지 마세요.]"
                ),
            },
        ]

        answer_parts: list[str] = []
        error_payload: dict[str, Any] | None = None
        try:
            async for chunk in stream_chat(llm_messages, []):
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    answer_parts.append(delta.content)
                    yield _sse("token", {"delta": delta.content})
        except LLMUnavailableError as exc:
            error_payload = {"error_code": "LLM_UNAVAILABLE", "message": exc.message}
        except Exception:
            logger.exception("consultation opening stream failed: session_id=%s", session_id)
            error_payload = {
                "error_code": "LLM_UNAVAILABLE",
                "message": "잠시 후 다시 시도해주세요",
            }

        if error_payload is not None:
            yield _sse("error", error_payload)
            return

        assistant_message = await _persist_assistant_turn(
            db, conversation_id, ChatMode.NORMAL, "".join(answer_parts), []
        )
        yield _sse(
            "done",
            {
                "message_id": str(assistant_message.id) if assistant_message else None,
                "applied_actions": [],
                "suggested_replies": await _generate_suggested_replies(
                    "".join(answer_parts)
                ),
            },
        )


async def stream_consultation_reply(
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    content: str,
) -> AsyncIterator[str]:
    """상담 챗봇의 대화 턴. stream_reply와 SSE 프레이밍/도구 루프는 같지만, 도구가
    실제 기록이 아니라 ConsultationSession.draft_plan만 바꾸고, 매 턴 끝에 readiness를
    알리는 signal 이벤트를 추가로 낸다 — 대화가 이어지면 이전 턴의 '준비됨'은
    취소된다는 요구를 여기서 구현한다."""
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if user is None:
            yield _sse("error", {"error_code": "USER_NOT_FOUND", "message": "사용자 없음"})
            return

        try:
            session = await consultation_service.get_session(db, user_id, session_id)
        except ConsultationSessionNotFoundError as exc:
            yield _sse(
                "error",
                {"error_code": "CONSULTATION_SESSION_NOT_FOUND", "message": exc.message},
            )
            return

        conversation_id = session.conversation_id
        conversation = await db.get(Conversation, conversation_id)

        user_message = Message(
            conversation_id=conversation_id,
            role=MessageRole.USER.value,
            content=content,
            mode=ChatMode.NORMAL.value,
        )
        db.add(user_message)
        if conversation is not None and conversation.title is None:
            conversation.title = " ".join(content.split())[:TITLE_LIMIT]

        # 이 턴이 다시 signal_ready_to_conclude를 부르지 않으면 '준비됨'이 취소된다 —
        # 대화가 이어졌다는 것 자체가 상담이 아직 안 끝났다는 뜻이기 때문이다.
        was_ready = session.status == ConsultationStatus.READY.value
        if was_ready:
            session.status = ConsultationStatus.IN_PROGRESS.value
            session.ready_at = None

        await _touch(db, conversation_id)
        await db.commit()

        history = await db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.id != user_message.id)
            .order_by(Message.created_at.desc())
            .limit(HISTORY_LIMIT)
        )
        context = await build_context(db, user)
        roadmap_summary = await consultation_service.get_active_plan_summary(db, user)

        llm_messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": build_consultation_system_prompt(
                    session.kind,
                    json.dumps(context, ensure_ascii=False),
                    json.dumps(roadmap_summary, ensure_ascii=False)
                    if roadmap_summary is not None
                    else None,
                ),
            }
        ]
        llm_messages.extend(
            {"role": m.role, "content": m.content} for m in reversed(list(history))
        )
        llm_messages.append({"role": "user", "content": content})
        # 졸업생 적합성 상담은 로드맵 도구 대신 학과 조회 도구만 준다. 계획을
        # 만들 수단(propose_draft_plan 등)은 아예 주지 않아, 챗봇이 로드맵을
        # 저장하려 시도할 수 없게 하면서도 목표 학과의 실제 입시 데이터는 조회하게 한다.
        is_graduate_fit = session.kind == ConsultationKind.GRADUATE_FIT.value
        consultation_tools = (
            GRADUATE_FIT_TOOL_SPECS if is_graduate_fit else CONSULTATION_TOOL_SPECS
        )

        applied_actions: list[dict[str, Any]] = []
        answer_parts: list[str] = []
        error_payload: dict[str, Any] | None = None

        try:
            for _ in range(MAX_TOOL_ROUNDS):
                round_text: list[str] = []
                tool_calls: dict[int, dict[str, Any]] = {}

                async for chunk in stream_chat(llm_messages, consultation_tools):
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta.content:
                        round_text.append(delta.content)
                    if delta.tool_calls:
                        _merge_tool_call_deltas(tool_calls, delta.tool_calls)

                raw_text = "".join(round_text)
                visible_text = filter_consultation_output_for_period(
                    raw_text,
                    target_grade=session.target_grade,
                    target_semester=session.target_semester,
                    school_record_status=context["school_record_coverage"]["status"],
                    has_declared_direction=bool(
                        (context.get("memory", {}).get("career_goal") or {}).get("goal")
                        or context.get("memory", {}).get("target_department")
                        or context.get("memory", {}).get("interest_keywords")
                    ),
                    has_current_course_data=any(
                        record.get("grade") == session.target_grade
                        and record.get("semester") == session.target_semester
                        for record in context.get("academic_performance", [])
                    ),
                    confirmed_plan_titles=[
                        str(node.get("title", "")) for node in (roadmap_summary or [])
                    ],
                )
                if visible_text:
                    if answer_parts:
                        answer_parts.append("\n\n")
                        yield _sse("token", {"delta": "\n\n"})
                    answer_parts.append(visible_text)
                    yield _sse("token", {"delta": visible_text})
                if not tool_calls:
                    break

                llm_messages.append(
                    {
                        "role": "assistant",
                        # 모델의 다음 도구 호출 문맥은 원문을 보존한다. 화면·저장용
                        # 문장만 학기 규칙 필터를 거친다.
                        "content": raw_text or None,
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
                        if is_graduate_fit:
                            result = await execute_graduate_fit_tool(
                                db, user, session, call["name"], arguments
                            )
                        else:
                            result = await execute_consultation_tool(
                                db, user, session, call["name"], arguments
                            )

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
                    "consultation tool loop hit the round limit: session_id=%s", session_id
                )
        except asyncio.CancelledError:
            await asyncio.shield(
                _persist_assistant_turn(
                    db,
                    conversation_id,
                    ChatMode.NORMAL,
                    "".join(answer_parts),
                    applied_actions,
                )
            )
            raise
        except LLMUnavailableError as exc:
            error_payload = {"error_code": "LLM_UNAVAILABLE", "message": exc.message}
        except Exception:
            logger.exception("consultation chat stream failed: session_id=%s", session_id)
            error_payload = {
                "error_code": "LLM_UNAVAILABLE",
                "message": "잠시 후 다시 시도해주세요",
            }

        assistant_message = await _persist_assistant_turn(
            db, conversation_id, ChatMode.NORMAL, "".join(answer_parts), applied_actions
        )

        if error_payload is not None:
            yield _sse("error", error_payload)
            return

        yield _sse(
            "done",
            {
                "message_id": str(assistant_message.id) if assistant_message else None,
                "applied_actions": applied_actions,
                "suggested_replies": await _generate_suggested_replies(
                    "".join(answer_parts)
                ),
            },
        )

        await db.refresh(session)
        yield _sse(
            "signal",
            {
                "ready": session.status == ConsultationStatus.READY.value,
                "full_replan_confirmed": session.full_replan_confirmed_at is not None,
            },
        )
