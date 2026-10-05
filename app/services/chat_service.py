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
from app.models.conversation import ChatMode, Conversation, Message, MessageRole, TitleSource
from app.models.user import User
from app.services import consultation_service, record_review_consultation
from app.services.chat.consultation_prompts import build_consultation_system_prompt
from app.services.chat.consultation_tools import (
    GRADUATE_FIT_TOOL_SPECS,
    execute_consultation_tool,
    execute_graduate_fit_tool,
    tools_for_stage,
)
from app.services.chat.context import build_context, prepare_context_for_chat
from app.services.chat.prompts import build_system_prompt
from app.services.chat.tools import TOOL_SPECS, execute_tool
from app.services.consultation_stage import remaining_periods, session_stage
from app.services.llm import call_structured, stream_chat
from app.services.subject_catalog import normalize as normalize_subject

logger = logging.getLogger(__name__)

# 대화에 실어 보내는 직전 메시지 수. 그 앞의 맥락은 <학생_데이터>가 대신한다.
HISTORY_LIMIT = 20
# 도구 호출 → 결과 → 다시 호출을 몇 번까지 허용할지. 무한 루프 방지용.
MAX_TOOL_ROUNDS = 4
TITLE_LIMIT = 60
# 제목을 대화 내용으로 짓는 시도는 학생 발화 몇 번째까지 할지. 첫 마디가 "안녕"처럼
# 주제가 없으면 다음 턴에 다시 시도하고, 이 횟수를 넘기면 첫 메시지로 대신한다.
TITLE_ATTEMPT_TURNS = 3

_GRADE_PERIOD = re.compile(r"([1-3])\s*학년(?:\s*([1-2])\s*학기)?")
# 요약에서 모델이 "1-1: …", "2-1(이번 학기)"처럼 줄여 쓰는 학기 표기. "1-2개"
# 같은 수량 표현과 헷갈리지 않도록 뒤에 콜론·괄호·쉼표·"학기"가 올 때만 인정한다.
_SHORT_PERIOD = re.compile(r"(?<![\d-])([1-3])-([1-2])(?=\s*(?:[:(（,)\]]|학기))")
# 마무리 버튼 안내. 필터가 "나가기 버튼"을 실제 버튼 이름(CONCLUDE_BUTTON_LABEL)으로 바꾼
# 뒤에도 같은 안내로 알아보도록 두 표현을 모두 잡는다.
_EXIT_NOTICE = re.compile(r"나가기\s*버튼|상담\s*마치고\s*메인\s*화면으로")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_BUTTON_FOLLOW_UP = re.compile(r"누르|눌러|버튼")
_LINE_PREFIX = re.compile(r"^[\s\-*•#>]*(?:\d+[.)]\s*)?")
# 줄머리로 보는 범위. "후보 1. 1학년 …"처럼 짧은 머리말 뒤에 오는 학기까지 포함한다.
_HEADING_PERIOD_MAX_OFFSET = 8
_LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s")
# 도구를 부르기 직전에 문장을 끝맺지 못하고 남긴 짧은 조각("그럼", "그러면 이제").
_DANGLING_FRAGMENT_MAX = 12
_SENTENCE_END = re.compile(r"[.!?…:)\]*]\s*$|[요다죠네까]\s*$")
_UNVERIFIED_COURSE_PLACEHOLDER = "관련 교과"
_REPEATED_COURSE_PLACEHOLDER = re.compile(
    rf"{_UNVERIFIED_COURSE_PLACEHOLDER}(?:\s*[·,/]\s*{_UNVERIFIED_COURSE_PLACEHOLDER})+"
    # "물리학Ⅰ 교과 개념"을 바꾸면 "관련 교과 교과 개념"이 되므로 뒤의 "교과"도 삼킨다.
    rf"|{_UNVERIFIED_COURSE_PLACEHOLDER}\s+교과(?![가-힣])"
)
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
    # "수학Ⅰ·Ⅱ"처럼 로마 숫자만 이어 붙인 표기도 한 과목명으로 삼킨다.
    r"(?:\s*[·/]\s*[ⅠⅡ]+)*"
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


# 마무리 버튼의 실제 이름. 모델이 옛 표현("나가기 버튼")을 쓰면 이 이름으로 바꾼다.
CONCLUDE_BUTTON_LABEL = "'상담 마치고 메인 화면으로' 버튼"
_EXIT_BUTTON_ALIAS = re.compile(r"['‘\"“]?나가기['’\"”]?\s*버튼")
# "아직 초안이에요, 버튼을 눌러야 확정돼요" 류의 안내. 매 턴 반복되면 학생이 지치므로
# 마무리 신호(signal_ready_to_conclude)를 보내는 턴에만 남긴다.
_CONCLUDE_NOTICE = re.compile(
    r"(?:나가기|메인\s*화면|상담\s*마치|마무리\s*버튼).{0,60}(?:눌러|누르|확정)"
    r"|다시\s*한\s*번\s*강조|아직\s*초안(?:이|일)|초안일\s*뿐",
)
def _strip_conclude_notice(text: str) -> str:
    lines = []
    for line in text.splitlines():
        sentences = _SENTENCE_SPLIT.split(line)
        kept = [sentence for sentence in sentences if not _CONCLUDE_NOTICE.search(sentence)]
        if kept or not line.strip():
            lines.append(" ".join(kept))
    return "\n".join(lines)


def _replace_unregistered_courses(text: str, course_names: list[str]) -> str:
    registered = {normalize_subject(name) for name in course_names}

    def keep_or_replace(match: re.Match[str]) -> str:
        # "공통수학1"처럼 정규식이 과목명 뒷부분만 잡을 수 있어, 바로 앞에 붙은 한글까지
        # 넓혀 온전한 과목명으로 비교한다.
        start = match.start()
        while start > 0 and "가" <= text[start - 1] <= "힣":
            start -= 1
        word = normalize_subject(text[start : match.end()])
        if word in registered or normalize_subject(match.group(0)) in registered:
            return match.group(0)
        return _UNVERIFIED_COURSE_PLACEHOLDER if start == match.start() else match.group(0)

    return _UNVERIFIED_SPECIFIC_COURSE.sub(keep_or_replace, text)


def _drop_dangling_fragment(text: str) -> str:
    """도구 호출 직전 라운드의 끝에 남은, 문장으로 끝맺지 못한 짧은 조각을 지운다.

    모델이 "그럼"까지만 쓰고 도구를 부르면, 다음 라운드 문장과 문단 구분으로
    이어 붙여져 뜬금없는 한 단어 문단이 남았다(실제 응답에서 관측).
    """
    lines = text.rstrip().splitlines()
    if lines:
        last = lines[-1].strip()
        if last and len(last) <= _DANGLING_FRAGMENT_MAX and not _SENTENCE_END.search(last):
            lines = lines[:-1]
    return "\n".join(lines)


def _period_index(grade: int, semester: int) -> int:
    return (grade - 1) * 2 + (semester - 1)


def _line_periods(line: str) -> list[int]:
    """한 줄이 언급하는 학기들의 순번. 학기 없이 학년만 쓰면 그 학년 1학기로 본다."""
    periods = [
        _period_index(int(grade), int(semester or "1"))
        for grade, semester in _GRADE_PERIOD.findall(line)
    ]
    periods.extend(
        _period_index(int(grade), int(semester))
        for grade, semester in _SHORT_PERIOD.findall(line)
    )
    return periods


def _heading_period(line: str) -> int | None:
    """줄머리(목록 기호·굵게 표시를 뺀 첫 몇 글자)에 적힌 학기 — 그 줄이 무엇에 관한
    줄인지. 본문 중간에 "1학년에서 다룬 것을 심화"처럼 지난 학기를 출처로 짚는
    것은 줄의 주제가 아니므로 None이다."""
    head = _LINE_PREFIX.sub("", line).replace("**", "").lstrip("[")
    candidates = [
        (match.start(), _period_index(int(match[1]), int(match[2] or "1")))
        for match in _GRADE_PERIOD.finditer(head)
    ] + [
        (match.start(), _period_index(int(match[1]), int(match[2])))
        for match in _SHORT_PERIOD.finditer(head)
    ]
    if not candidates:
        return None
    position, period = min(candidates)
    return period if position <= _HEADING_PERIOD_MAX_OFFSET else None


def _drop_repeated_exit_notice(text: str, *, already_given: bool) -> str:
    """한 턴 안에서 마무리 버튼 안내는 처음 한 문장만 남긴다.

    도구 호출 전후 라운드에 걸쳐, 또 한 문단 안에서도 모델이 같은 안내를 두세 번
    되풀이한 실제 응답이 있었다. already_given이면 이 텍스트의 안내 문장을 모두
    지운다.
    """
    given = already_given
    kept_lines: list[str] = []
    for line in text.splitlines():
        kept_sentences: list[str] = []
        dropped_notice = False
        for sentence in _SENTENCE_SPLIT.split(line):
            if _EXIT_NOTICE.search(sentence):
                if given:
                    dropped_notice = True
                    continue
                given = True
            elif dropped_notice and _BUTTON_FOLLOW_UP.search(sentence):
                # "지금 누르시면 돼요"처럼 방금 지운 안내에 기대는 문장도 함께 지운다.
                continue
            dropped_notice = False
            kept_sentences.append(sentence)
        if kept_sentences or not line.strip():
            kept_lines.append(" ".join(kept_sentences))
    return "\n".join(kept_lines)


def filter_consultation_output_for_period(
    text: str,
    *,
    target_grade: int,
    target_semester: int,
    school_record_status: str = "imported",
    has_declared_direction: bool = False,
    has_current_course_data: bool = True,
    confirmed_plan_titles: list[str] | None = None,
    allow_conclude_notice: bool = True,
    current_course_names: list[str] | None = None,
) -> str:
    """현재보다 앞선 학기를 새 계획처럼 보이는 상담 문장에서 제거한다.

    DeepSeek가 프롬프트의 '과거는 회고' 규칙을 무시한 실제 응답이 있었기 때문에,
    학생에게 보내기 직전에 다시 검사한다. 한 줄에 과거 학기가 들어 있으면 통째로
    버린다. 과거·현재를 한 줄에 섞어 버린 모델 문장을 보존하는 것보다, 현재와 미래
    계획만 남기는 편이 안전하다.
    """
    current = _period_index(target_grade, target_semester)
    kept: list[str] = []
    # 과거 학기를 머리로 단 목록 항목을 지우면, 그 아래 들여쓴 설명 줄도 함께
    # 지운다. 머리만 지우면 어느 학기 얘기인지 모를 설명만 덩그러니 남았다(실제
    # 응답에서 관측 — 3개년 로드맵을 "- **1학년 1학기 — 주제**" 다음 줄에 설명을
    # 들여 쓰는 형식으로 답할 때).
    dropping_item_body = False
    for line in text.splitlines():
        if dropping_item_body:
            if line.strip() and line[:1].isspace() and not _LIST_ITEM.match(line):
                continue
            dropping_item_body = False
        # 지난 학기에 관한 줄(줄머리에 지난 학기가 적힌 줄)만 지운다. 이전에는 한
        # 번이라도 지난 학기를 언급하면 지웠는데, "2학년: 1학년에서 다룬 원리를
        # 심화"처럼 인과 사슬을 설명하는 현재·미래 줄까지 사라졌다(실제 응답에서 관측).
        heading = _heading_period(line)
        mentions_past = heading is not None and heading < current
        if not mentions_past:
            kept.append(line)
        elif _LIST_ITEM.match(line):
            dropping_item_body = True

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
    # 중립적인 표현으로 바꾼다. 과목을 등록했으면 등록한 과목명은 그대로 둔다.
    # 다음 학기 이후를 말하는 줄은 건드리지 않는다 — 앞으로 들을 과목을 연계
    # 교과로 제안하는 것은 수강 사실을 단정하는 말이 아니다.
    if not has_current_course_data or current_course_names:
        registered = current_course_names or []
        filtered = "\n".join(
            line
            if any(period > current for period in _line_periods(line))
            else _REPEATED_COURSE_PLACEHOLDER.sub(
                _UNVERIFIED_COURSE_PLACEHOLDER,
                _replace_unregistered_courses(line, registered),
            )
            for line in filtered.splitlines()
        )

    # 초안 도구의 재시도는 모델 내부 처리일 뿐 학생이 볼 오류가 아니다. 또한
    # 상담 완료 전에는 계획이 확정·저장된 것이 아니므로 표현을 바로잡는다.
    filtered = _INTERNAL_DRAFT_RETRY.sub("", filtered)
    # 마무리 버튼은 이름이 정해져 있다 — "나가기 버튼"은 실제 화면에 없는 이름이다.
    filtered = _EXIT_BUTTON_ALIAS.sub(CONCLUDE_BUTTON_LABEL, filtered)
    # "초안이에요, 버튼을 눌러야 확정돼요"는 마무리 신호를 보내는 턴에만 한 번 말한다.
    # 프롬프트로 부탁했지만 거의 매 턴 반복하는 실제 응답이 있어 코드로 막는다.
    if not allow_conclude_notice:
        filtered = _strip_conclude_notice(filtered)
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
    # 실제 DeepSeek 응답을 막지 못했다. 학생부 처리가 아직 안 끝났으면(업로드는
    # 했다) 문장 자체를 제거하고 확인 범위를 명시한 사실 문장으로 바꾼다.
    #
    # not_uploaded(애초에 올린 적이 없는 학생)는 여기서 뺀다 — "아직 반영되지
    # 않았다"는 처리 중인 일에 쓰는 말인데, 이 학생에게는 매 턴 반복해서 그렇게
    # 말하는 것 자체가 어색하고 불필요하다(사용자 피드백). 이 학생에게는 과대
    # 단정 문장만 조용히 지우고 별도 안내문을 매번 덧붙이지 않는다 — 시스템
    # 프롬프트(3-2)가 필요하면 한 번만 자연스럽게 짚도록 이미 안내한다.
    if school_record_status in _RECORD_COVERAGE_UNAVAILABLE:
        lines = filtered.splitlines()
        kept_lines = [line for line in lines if not _UNVERIFIED_RECORD_ABSENCE.search(line)]
        if len(kept_lines) != len(lines):
            if school_record_status == "not_uploaded":
                filtered = "\n".join(kept_lines)
            else:
                notice = (
                    "학생부가 아직 반영되지 않아 이전 활동의 존재 여부는 확인할 수 "
                    "없습니다. 현재 저장된 기록이 비어 있다는 사실만으로 활동이 "
                    "없었다고 판단하지 않습니다."
                )
                filtered = notice + "\n\n" + "\n".join(kept_lines)

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


async def rename_conversation(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID, title: str
) -> Conversation:
    """학생이 직접 고친 제목. 이후 자동 제목 생성은 이 대화를 건드리지 않는다."""
    conversation = await get_conversation(db, user_id, conversation_id)
    conversation.title = title
    conversation.title_source = TitleSource.USER.value
    await db.commit()
    await db.refresh(conversation)
    return conversation


class _ConversationTitle(BaseModel):
    title: str = ""


_TITLE_PROMPT = """너는 고등학생 진로·학습 상담 앱의 대화 목록에 붙일 제목을 짓는다.
학생이 한 말들과 상담 AI의 답변 일부를 보고, 이 대화가 무엇에 관한 것인지 한눈에
알 수 있는 짧은 제목을 지어라.

[규칙]
1. 한국어 명사구로 6~18자. 문장·질문·존댓말 어미로 쓰지 마라
   (좋은 예: "수학Ⅱ 탐구 기록 연결", "2학년 활동 약점 점검", "물리 탐구 주제 고르기").
2. 학생의 첫 말을 그대로 옮기지 말고 주제를 요약하라.
3. 인사말·잡담뿐이라 주제를 알 수 없으면 빈 문자열을 돌려줘라.
4. 따옴표·이모지·마침표를 넣지 마라.
5. 반드시 아래 JSON만 출력하라: {"title": "..."}"""


def _clean_title(raw: str) -> str:
    title = " ".join((raw or "").split()).strip(" \"'“”‘’.·-")
    return title[:TITLE_LIMIT]


async def _maybe_generate_title(
    db: AsyncSession, conversation_id: uuid.UUID, last_answer: str
) -> str | None:
    """일반 대화의 제목을 대화 주제로 짓는다. 학생이 고친 제목이나 이미 지은 제목은
    건드리지 않는다. 실패해도 답변 흐름을 막지 않도록 예외를 삼킨다."""
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.title is not None:
        return None

    user_texts = list(
        await db.scalars(
            select(Message.content)
            .where(
                Message.conversation_id == conversation_id,
                Message.role == MessageRole.USER.value,
            )
            .order_by(Message.created_at.asc())
            .limit(TITLE_ATTEMPT_TURNS + 1)
        )
    )
    if not user_texts:
        return None

    title = ""
    try:
        result = await call_structured(
            _TITLE_PROMPT,
            json.dumps(
                {
                    "student_messages": user_texts[:TITLE_ATTEMPT_TURNS],
                    "assistant_last_answer": (last_answer or "")[:600],
                },
                ensure_ascii=False,
            ),
            _ConversationTitle,
        )
        title = _clean_title(result.title)
    except Exception:
        logger.warning("conversation title generation failed", exc_info=True)

    if not title:
        if len(user_texts) < TITLE_ATTEMPT_TURNS:
            # 아직 주제가 드러나지 않았다 — 다음 턴에 다시 시도한다.
            return None
        title = _clean_title(user_texts[0]) or "새 대화"

    await db.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id, Conversation.title.is_(None))
        .values(title=title, title_source=TitleSource.AUTO.value)
    )
    await db.commit()
    return title


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
            await get_conversation(db, user_id, conversation_id)
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
        # 제목은 첫 메시지 원문을 자르지 않고, 답변이 끝난 뒤 대화 주제를 읽어 짓는다
        # (_maybe_generate_title).
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

        # 답변을 먼저 끝까지 보낸 뒤에 제목을 짓는다 — 제목 생성이 느리거나 실패해도
        # 학생이 받는 답변에는 영향이 없어야 한다.
        title = await _maybe_generate_title(db, conversation_id, "".join(answer_parts))
        if title:
            yield _sse("title", {"conversation_id": str(conversation_id), "title": title})


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


def consultation_progress(session: Any) -> dict[str, Any]:
    """<상담_진행_상태>에 넘길 사실들. 모두 세션에 저장된 값에서 계산한다."""
    return {
        "stage": session_stage(session),
        "target_label": f"{session.target_grade}학년 {session.target_semester}학기",
        "remaining_semesters": [
            f"{g}학년 {s}학기"
            for g, s in remaining_periods(session.target_grade, session.target_semester)
        ],
        "flow": session.draft_flow,
        "flow_confirmed": session.flow_confirmed_at is not None,
        "semester_goal": session.semester_goal,
        "has_draft_plan": session.draft_plan is not None,
    }


def consultation_signal(session: Any) -> dict[str, Any]:
    """매 턴 끝에 화면에 알리는 상태 — 마무리 버튼, 흐름 카드, 진행 단계 표시용."""
    return {
        "ready": session.status == ConsultationStatus.READY.value,
        "full_replan_confirmed": session.full_replan_confirmed_at is not None,
        "stage": session_stage(session),
        "flow": session.draft_flow,
        "flow_confirmed": session.flow_confirmed_at is not None,
        "semester_goal": session.semester_goal,
    }


async def consultation_signal_for(db: AsyncSession, session: Any) -> dict[str, Any]:
    """signal 이벤트 내용. 생기부 확인 상담은 흐름 카드 대신 확인 현황을 싣는다."""
    if session.kind == ConsultationKind.RECORD_REVIEW.value:
        return {
            "ready": session.status == ConsultationStatus.READY.value,
            "stage": session_stage(session),
            "record_review": await record_review_consultation.state(db, session),
        }
    return consultation_signal(session)


def _known_plan_titles(session: Any, roadmap_summary: list[dict] | None) -> list[str]:
    """출력 필터가 '이미 계획에 있다'는 문장을 허용할 근거 — 확정된 로드맵 제목과
    이 상담에서 실제로 저장한 흐름·학기 목표 제목. 여기 없는 제목을 기존 계획처럼
    말하는 문장은 필터가 걸러낸다."""
    titles = [str(node.get("title", "")) for node in (roadmap_summary or [])]
    for node in (session.draft_flow or {}).get("nodes", []):
        titles.append(str(node.get("title", "")))
    if session.semester_goal:
        titles.append(str(session.semester_goal.get("title", "")))
    return [t for t in titles if t]


def _opening_instruction(session: Any) -> str:
    base = (
        "[시스템 안내: 지금 상담 화면이 막 열렸고 학생은 아직 아무 말도 하지 않았습니다. "
        "진단 결과와 학생 데이터를 근거로, 학생에게 먼저 건네는 여는 말을 한 번 해주세요. "
        "무엇을 근거로 보고 있는지 짧게 밝히세요. 도구는 호출하지 마세요. "
        "안내문처럼 길게 나열하지 말고 3~5문장 안팎으로 대화하듯 쓰세요. 진단 결과가 비어 "
        "있으면 '진단 리포트를 봤다', '방금 분석했다'고 말하지 말고 지금 실제로 가진 정보"
        "(학생이 답한 진로·관심, 학생부 반영 상태)만으로 시작한다고 말하세요. "
    )
    stage = session_stage(session)
    if stage == "flow":
        return base + (
            "이번 상담은 3학년 말의 도착점을 먼저 정하고, 거기로 가는 3개년 흐름을 잡은 뒤, 그 "
            "안에서 이번 학기 목표와 주제를 정하는 순서로 진행된다고 한 문장으로 알려 주세요. "
            "기록이 있으면 지금까지의 출발점을 한두 문장으로 짚고, 진로 정보를 바탕으로 도착점 "
            "후보를 한 문장으로 제시한 뒤 그 도착점이 맞는지 한 가지만 물어보세요. 이번 학기의 "
            "과목·활동·주제는 아직 꺼내지 마세요.]"
        )
    if stage == "semester_goal":
        return base + (
            "3개년 흐름을 한두 문장으로 되짚고, 그 흐름이 여전히 맞는지 확인하는 질문 "
            "한 가지로 대화를 시작하세요.]"
        )
    return base + "학생이 어떤 이야기부터 꺼내면 좋을지 한 가지만 물어보세요.]"


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

        if session.kind == ConsultationKind.RECORD_REVIEW.value:
            system_prompt = record_review_consultation.build_prompt(
                record_review_consultation.student_facts(user),
                await record_review_consultation.state(db, session),
            )
            instruction = record_review_consultation.opening_instruction()
        else:
            context = await build_context(db, user)
            roadmap_summary = await consultation_service.get_active_plan_summary(db, user)
            system_prompt = build_consultation_system_prompt(
                session.kind,
                json.dumps(context, ensure_ascii=False),
                json.dumps(roadmap_summary, ensure_ascii=False)
                if roadmap_summary is not None
                else None,
                consultation_progress(session),
            )
            instruction = _opening_instruction(session)
        # 학생 발화 대신, 여는 말을 건네라는 지시를 준다. 이 지시문은 저장하지 않고
        # (학생에게 보이지 않아야 한다), 생성된 인사만 어시스턴트 메시지로 남긴다.
        llm_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": instruction},
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
        # 상담 대화의 제목은 세션을 만들 때 목적에 맞게 정해 둔다(예: "3개년 흐름 설계").
        # 예전 세션처럼 제목이 비어 있으면 같은 규칙으로 채운다.
        if conversation is not None and conversation.title is None:
            conversation.title = consultation_service.default_consultation_title(
                session.kind, session.target_grade, session.target_semester
            )
            conversation.title_source = TitleSource.DEFAULT.value

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
        # 생기부 확인 상담은 학기 계획 상담과 재료·도구·출력 규칙이 모두 다르다. 로드맵을
        # 바꿀 도구는 주지 않는다(추천만 가능).
        is_record_review = session.kind == ConsultationKind.RECORD_REVIEW.value
        if is_record_review:
            context: dict[str, Any] = {}
            roadmap_summary = None
            system_prompt = record_review_consultation.build_prompt(
                record_review_consultation.student_facts(user),
                await record_review_consultation.state(db, session),
            )
        else:
            context = await build_context(db, user)
            roadmap_summary = await consultation_service.get_active_plan_summary(db, user)
            system_prompt = build_consultation_system_prompt(
                session.kind,
                json.dumps(context, ensure_ascii=False),
                json.dumps(roadmap_summary, ensure_ascii=False)
                if roadmap_summary is not None
                else None,
                consultation_progress(session),
            )

        llm_messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        llm_messages.extend(
            {"role": m.role, "content": m.content} for m in reversed(list(history))
        )
        llm_messages.append({"role": "user", "content": content})
        # 졸업생 적합성 상담은 로드맵 도구 대신 학과 조회 도구만 준다. 계획을
        # 만들 수단(propose_draft_plan 등)은 아예 주지 않아, 챗봇이 로드맵을
        # 저장하려 시도할 수 없게 하면서도 목표 학과의 실제 입시 데이터는 조회하게 한다.
        is_graduate_fit = session.kind == ConsultationKind.GRADUATE_FIT.value
        # 도구 목록은 이 턴을 시작할 때의 단계로 한 번 정한다(tools_for_stage 참고).
        if is_record_review:
            consultation_tools = record_review_consultation.TOOL_SPECS
        elif is_graduate_fit:
            consultation_tools = GRADUATE_FIT_TOOL_SPECS
        else:
            consultation_tools = tools_for_stage(session)
        # 이 턴에 마무리 신호를 보냈는지 — 그 턴에만 확정 버튼 안내를 허용한다.
        signalled_conclude = False

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
                signalled_conclude = signalled_conclude or any(
                    call["name"] == "signal_ready_to_conclude" for call in tool_calls.values()
                )
                spoken = _drop_dangling_fragment(raw_text) if tool_calls else raw_text
                # 생기부 확인은 지난 학기 기록을 두고 이야기하는 대화다 — 학기 계획용 필터를
                # 거치면 "1학년 1학기 성적이 달라요" 같은 문장이 통째로 지워진다.
                visible_text = (
                    spoken
                    if is_record_review
                    else filter_consultation_output_for_period(
                        spoken,
                        target_grade=session.target_grade,
                        target_semester=session.target_semester,
                        school_record_status=context["school_record_coverage"]["status"],
                        has_declared_direction=bool(
                            (context.get("memory", {}).get("career_goal") or {}).get("goal")
                            or context.get("memory", {}).get("target_department")
                            or context.get("memory", {}).get("interest_keywords")
                        ),
                        has_current_course_data=bool(context.get("current_semester_courses"))
                        or any(
                            record.get("grade") == session.target_grade
                            and record.get("semester") == session.target_semester
                            for record in context.get("academic_performance", [])
                        ),
                        confirmed_plan_titles=_known_plan_titles(session, roadmap_summary),
                        allow_conclude_notice=signalled_conclude or is_graduate_fit,
                        current_course_names=[
                            str(course.get("subject", ""))
                            for course in context.get("current_semester_courses", [])
                        ],
                    )
                )
                visible_text = _drop_repeated_exit_notice(
                    visible_text,
                    already_given=any(_EXIT_NOTICE.search(part) for part in answer_parts),
                ).strip()
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
                        if is_record_review:
                            result = await record_review_consultation.execute_tool(
                                db, session, call["name"], arguments
                            )
                        elif is_graduate_fit:
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

                # 마무리 신호가 받아들여졌고 이 턴에 이미 학생에게 한 말이 있으면
                # 여기서 턴을 끝낸다. 한 라운드를 더 돌리면 모델이 방금 한 요약과
                # "나가기 버튼" 안내를 다시 되풀이했다(실제 응답에서 관측).
                if answer_parts and any(
                    action["tool"] == "signal_ready_to_conclude"
                    and "error" not in (action["result"] or {})
                    for action in applied_actions
                ):
                    break
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
        yield _sse("signal", await consultation_signal_for(db, session))
