"""상담 챗봇 전용 도구. 일반 챗봇(tools.py)과 달리 실제 활동/기록을 건드리지 않고,
오직 ConsultationSession.draft_plan(초안)과 상태만 바꾼다 — 확정은 학생이 명시적으로
누르는 conclude 엔드포인트에서만 일어난다("버튼을 누르기 전까지는 확정이 아니다").

'프롬프트는 부탁, 코드가 보증' 원칙에 따라, 재평가 상담이 학생의 명시 동의
(full_replan_confirmed_at) 없이 전체 계획을 다시 쓰려는 시도는 프롬프트가 아니라
이 파일의 핸들러가 실제로 거부한다.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.consultation import ConsultationKind, ConsultationSession, ConsultationStatus
from app.models.user import User
from app.schemas.consultation import DraftPlan

_STAGE_NAMES = ["탐색", "기초", "연결", "분화", "독립 탐구", "종합"]


async def _propose_draft_plan(
    db: AsyncSession, user: User, session: ConsultationSession, args: dict[str, Any]
) -> dict[str, Any]:
    mode = args.get("mode")
    if (
        mode == "full_replan"
        and session.kind == ConsultationKind.SEMESTER_REVIEW.value
        and session.full_replan_confirmed_at is None
    ):
        return {
            "error": (
                "학생의 명시적 확인 없이는 전체 계획을 다시 세울 수 없습니다. "
                "propose_full_replan_exception으로 먼저 제안하고 학생이 확인 버튼을 "
                "누른 뒤에 다시 시도하세요."
            )
        }

    try:
        draft = DraftPlan.model_validate(args)
    except ValidationError as exc:
        return {"error": f"제안 형식이 올바르지 않습니다: {exc.errors()[0]['msg']}"}

    if len(draft.plan_events) != 10:
        return {"error": "plan_events는 정확히 10개여야 합니다(core 4개 + optional 6개 권장)"}
    if draft.mode == "full_replan" and len(draft.nodes) != 6:
        return {
            "error": "mode가 full_replan이면 nodes는 정확히 6개(1학년 1학기~3학년 2학기)여야 합니다"
        }

    session.draft_plan = draft.model_dump(mode="json")
    await db.commit()
    return {
        "stored": True,
        "mode": draft.mode,
        "current_node_title": draft.current_node.title,
        "plan_events_count": len(draft.plan_events),
    }


async def _propose_full_replan_exception(
    db: AsyncSession, user: User, session: ConsultationSession, args: dict[str, Any]
) -> dict[str, Any]:
    if session.kind != ConsultationKind.SEMESTER_REVIEW.value:
        return {"error": "재평가 상담에서만 전체 재설계를 제안할 수 있습니다"}
    rationale = args.get("rationale", "")
    if not rationale:
        return {"error": "rationale(왜 전체를 다시 세워야 하는지)을 함께 채워주세요"}
    # 여기서는 아무것도 저장하지 않는다 — 이 결과가 SSE action 이벤트로 프론트에
    # 그대로 노출되고, 프론트가 명시적 Yes/No 다이얼로그를 띄운다. 실제 동의는
    # POST /consultation/sessions/{id}/confirm-full-replan로만 기록된다.
    return {"proposed": True, "rationale": rationale}


async def _signal_ready_to_conclude(
    db: AsyncSession, user: User, session: ConsultationSession, args: dict[str, Any]
) -> dict[str, Any]:
    if session.draft_plan is None:
        return {"error": "아직 제안된 계획이 없습니다 — propose_draft_plan을 먼저 호출하세요"}
    session.status = ConsultationStatus.READY.value
    session.ready_at = datetime.now(UTC)
    await db.commit()
    return {"ready": True, "summary": args.get("summary", "")}


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


_NODE_SCHEMA = {
    "type": "object",
    "properties": {
        "grade": {"type": "integer"},
        "semester": {"type": "integer"},
        "narrative_stage": {"type": "string", "enum": _STAGE_NAMES},
        "title": {"type": "string"},
        "objective": {"type": "string"},
        "candidate_subjects": {"type": "array", "items": {"type": "string"}},
        "competency_goals": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["grade", "semester", "narrative_stage", "title", "objective"],
}

_PLAN_EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "order_index": {"type": "integer"},
        "month_day": {"type": "string", "description": "MM-DD"},
        "category": {"type": "string"},
        "subject": {"type": "string"},
        "priority": {"type": "string", "enum": ["core", "optional"]},
        "title": {"type": "string"},
        "description": {"type": "string"},
    },
    "required": ["order_index", "month_day", "priority", "title"],
}

TOOL_SPECS: list[dict[str, Any]] = [
    _tool(
        "propose_draft_plan",
        "지금까지 대화로 정한 계획을 초안으로 저장한다(아직 확정 아님). 최초 상담이나 "
        "재평가의 전체 재설계에서는 mode=full_replan과 nodes(정확히 6개, 1학년 1학기~"
        "3학년 2학기 순서)를 채운다. 재평가의 기본 경로에서는 mode=current_node_only로 "
        "nodes를 비운다. current_node(이번 학기 목표)와 plan_events(이번 학기에 바로 "
        "실행할 탐구 주제 10개, core 4 + optional 6)는 매번 채운다. 학생이 반려하면 "
        "다시 호출해 덮어써라.",
        {
            "mode": {"type": "string", "enum": ["full_replan", "current_node_only"]},
            "career_track": {"type": "string"},
            "focus": {"type": "string"},
            "nodes": {"type": "array", "items": _NODE_SCHEMA},
            "current_node": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "objective": {"type": "string"},
                    "candidate_subjects": {"type": "array", "items": {"type": "string"}},
                    "competency_goals": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "objective"],
            },
            "plan_events": {"type": "array", "items": _PLAN_EVENT_SCHEMA},
        },
        ["mode", "current_node", "plan_events"],
    ),
    _tool(
        "propose_full_replan_exception",
        "재평가 상담에서만 쓴다. 학생의 상황(진로 전환 등)이 기존 3개년 큰 계획의 "
        "전제 자체를 무너뜨렸다고 판단될 때만, 처음부터 다시 세우자고 제안한다. "
        "이 호출만으로는 아무것도 바뀌지 않는다 — 학생이 화면의 별도 확인 버튼을 "
        "눌러야 실제로 전체 재설계가 허용된다.",
        {"rationale": {"type": "string", "description": "왜 전체를 다시 세워야 하는지"}},
        ["rationale"],
    ),
    _tool(
        "signal_ready_to_conclude",
        "상담이 충분히 마무리됐다고 판단되면 호출한다. propose_draft_plan으로 계획을 "
        "저장한 뒤에만 호출할 수 있다. 이후 학생이 화면의 나가기 버튼을 눌러야 실제로 "
        "확정된다 — 대화가 이어지면 이 신호는 취소되니, 정말 끝났을 때만 불러라.",
        {"summary": {"type": "string", "description": "무엇을 확정했는지 한두 문장 요약"}},
        ["summary"],
    ),
]

TOOL_HANDLERS = {
    "propose_draft_plan": _propose_draft_plan,
    "propose_full_replan_exception": _propose_full_replan_exception,
    "signal_ready_to_conclude": _signal_ready_to_conclude,
}


async def execute_consultation_tool(
    db: AsyncSession,
    user: User,
    session: ConsultationSession,
    name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return {"error": f"알 수 없는 도구입니다: {name}"}
    try:
        return await handler(db, user, session, args)
    except AppError as exc:
        return {"error": exc.message}
    except Exception as exc:
        await db.rollback()
        return {"error": f"{type(exc).__name__}: {exc}"}
