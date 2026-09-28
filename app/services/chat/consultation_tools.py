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
from app.schemas.consultation import DraftCurrentNode, DraftPlan, DraftPlanEvent
from app.services import admission_fit_service
from app.services.consultation_stage import (
    NARRATIVE_STAGE_NAMES,
    STAGE_FLOW,
    STAGE_SEMESTER_GOAL,
    STAGE_TOPICS,
    STAGE_WRAP_UP,
    needs_flow,
    period_index,
    session_stage,
    validate_flow_nodes,
)
from app.services.roadmap_service import get_active_roadmap

_STAGE_NAMES = NARRATIVE_STAGE_NAMES

# 지나간 학기 자리 — 흐름 초안에는 모델이 쓰지 않고 서버가 채운다. 확정 시
# _apply_full_replan이 어차피 회고 마디로 덮어쓰므로 여기서는 형태만 맞춘다.
_PAST_PLACEHOLDER_TITLE = "지금까지의 기록"
_PAST_PLACEHOLDER_OBJECTIVE = "실제 학생부 기록으로 확인하는 지나간 학기입니다."


def _reset_after_flow_change(session: ConsultationSession) -> None:
    """흐름이 바뀌면 그 위에 쌓은 학기 목표·주제 초안은 근거를 잃는다."""
    session.flow_confirmed_at = None
    session.semester_goal = None
    _reset_after_goal_change(session)


def _reset_after_goal_change(session: ConsultationSession) -> None:
    session.draft_plan = None
    if session.status == ConsultationStatus.READY.value:
        session.status = ConsultationStatus.IN_PROGRESS.value
        session.ready_at = None


async def _propose_three_year_flow(
    db: AsyncSession, user: User, session: ConsultationSession, args: dict[str, Any]
) -> dict[str, Any]:
    if not needs_flow(session.kind, session.full_replan_confirmed_at is not None):
        return {
            "error": (
                "이 상담은 기존 3개년 흐름을 유지한 채 이번 학기를 점검하는 상담입니다. "
                "흐름 자체를 다시 세워야 하면 propose_full_replan_exception으로 먼저 "
                "제안하고 학생이 확인 버튼을 누른 뒤에 시도하세요."
            )
        }

    nodes, error = validate_flow_nodes(
        args.get("nodes"), session.target_grade, session.target_semester
    )
    if error:
        return {"error": error}
    assert nodes is not None

    flow = {
        "career_track": str(args.get("career_track") or "").strip(),
        "destination": str(args.get("destination") or "").strip(),
        "focus": str(args.get("focus") or "").strip(),
        "so_far": str(args.get("so_far") or "").strip(),
        "nodes": nodes,
    }
    if session.draft_flow != flow:
        session.draft_flow = flow
        _reset_after_flow_change(session)
    await db.commit()
    return {
        "stored": True,
        "confirmed": session.flow_confirmed_at is not None,
        "semesters": [f"{n['grade']}학년 {n['semester']}학기" for n in nodes],
        "next": (
            "학생에게 흐름을 짧게 보여주고 반응을 받으세요. 학생이 동의하면 화면의 "
            "'이 흐름으로 확정' 버튼을 눌러 달라고 안내하세요. 버튼을 누르기 전에는 "
            "이번 학기 목표로 넘어갈 수 없습니다."
        ),
    }


def _current_flow_node(session: ConsultationSession) -> dict[str, Any] | None:
    flow = session.draft_flow or {}
    for node in flow.get("nodes", []):
        if (node.get("grade"), node.get("semester")) == (
            session.target_grade,
            session.target_semester,
        ):
            return node
    return None


async def _set_semester_goal(
    db: AsyncSession, user: User, session: ConsultationSession, args: dict[str, Any]
) -> dict[str, Any]:
    if session_stage(session) == STAGE_FLOW:
        return {
            "error": (
                "3개년 흐름이 아직 확정되지 않았습니다. 흐름을 먼저 학생과 조율하고, "
                "학생이 화면의 확정 버튼을 누른 뒤에 이번 학기 목표를 정하세요."
            )
        }
    try:
        goal = DraftCurrentNode.model_validate(args)
    except ValidationError as exc:
        return {"error": f"목표 형식이 올바르지 않습니다: {exc.errors()[0]['msg']}"}
    if not goal.title.strip() or not goal.objective.strip():
        return {"error": "title과 objective를 모두 채워주세요"}

    stored = goal.model_dump(mode="json")
    if session.semester_goal != stored:
        session.semester_goal = stored
        _reset_after_goal_change(session)
    await db.commit()
    return {
        "stored": True,
        "title": goal.title,
        "next": "이 목표에서 출발해 구체 탐구 주제를 학생과 2~3개씩 좁혀 가세요.",
    }


async def _existing_career_track(db: AsyncSession, user: User) -> str:
    roadmap = await get_active_roadmap(db, user.id)
    return roadmap.career_track if roadmap else ""


def _flow_nodes_for_all_semesters(session: ConsultationSession) -> list[dict[str, Any]]:
    """확정 저장에 쓰는 6개 마디 — 지나간 학기는 서버가 회고 자리로 채운다."""
    flow_nodes = {
        (n["grade"], n["semester"]): n for n in (session.draft_flow or {}).get("nodes", [])
    }
    current = period_index(session.target_grade, session.target_semester)
    nodes: list[dict[str, Any]] = []
    for index in range(6):
        grade, semester = index // 2 + 1, index % 2 + 1
        if index < current or (grade, semester) not in flow_nodes:
            nodes.append(
                {
                    "grade": grade,
                    "semester": semester,
                    "narrative_stage": _STAGE_NAMES[index],
                    "title": _PAST_PLACEHOLDER_TITLE,
                    "objective": _PAST_PLACEHOLDER_OBJECTIVE,
                    "candidate_subjects": [],
                    "competency_goals": [],
                }
            )
        else:
            nodes.append(flow_nodes[(grade, semester)])
    return nodes


async def _propose_draft_plan(
    db: AsyncSession, user: User, session: ConsultationSession, args: dict[str, Any]
) -> dict[str, Any]:
    stage = session_stage(session)
    if stage == STAGE_FLOW:
        return {
            "error": (
                "3개년 흐름이 아직 확정되지 않았습니다. 흐름 → 이번 학기 목표 → 주제 "
                "순서로 진행하세요. 지금은 propose_three_year_flow로 흐름을 제안할 차례입니다."
            )
        }
    if session.semester_goal is None:
        return {
            "error": (
                "이번 학기 목표가 아직 정해지지 않았습니다. 학생과 목표를 합의한 뒤 "
                "set_semester_goal을 먼저 호출하세요."
            )
        }

    events_raw = args.get("plan_events")
    try:
        events = [DraftPlanEvent.model_validate(e) for e in (events_raw or [])]
    except ValidationError as exc:
        return {"error": f"주제 형식이 올바르지 않습니다: {exc.errors()[0]['msg']}"}
    if len(events) != 10:
        return {"error": "plan_events는 정확히 10개여야 합니다(core 4개 + optional 6개 권장)"}

    goal = DraftCurrentNode.model_validate(session.semester_goal)
    if needs_flow(session.kind, session.full_replan_confirmed_at is not None):
        flow = session.draft_flow or {}
        draft = DraftPlan(
            mode="full_replan",
            career_track=flow.get("career_track", ""),
            focus=flow.get("focus", ""),
            nodes=_flow_nodes_for_all_semesters(session),
            current_node=goal,
            plan_events=events,
        )
    else:
        career_track = await _existing_career_track(db, user)
        draft = DraftPlan(
            mode="current_node_only",
            career_track=career_track,
            current_node=goal,
            plan_events=events,
        )

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
    if session.draft_plan is None or session_stage(session) != STAGE_WRAP_UP:
        return {
            "error": (
                "아직 정리된 주제 초안이 없습니다 — 흐름 → 이번 학기 목표 → "
                "propose_draft_plan 순서를 먼저 마치세요."
            )
        }
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


_FLOW_NODE_SCHEMA = {
    "type": "object",
    "properties": {
        "grade": {"type": "integer"},
        "semester": {"type": "integer"},
        "narrative_stage": {"type": "string", "enum": _STAGE_NAMES},
        "title": {
            "type": "string",
            "description": (
                "그 학기의 큰 방향을 한 줄로 — 추상적 수식어('기초 탐색', '역량 강화') 대신 "
                "10~30자 내외의 구체적 학술 테마(예: '불 대수 기반 디지털 논리 회로의 연산 원리')"
            ),
        },
        "objective": {
            "type": "string",
            "description": "그 학기에 무엇을 향해 가는지 1~2문장(구체적 개념·원리로)",
        },
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
        "propose_three_year_flow",
        "[1단계] 학생과 합의한 도착점(destination)과, 거기로 가는 3개년 큰 흐름을 초안으로 "
        "저장한다. nodes에는 **현재 학기부터 3학년 2학기까지** 남은 학기를 하나씩 순서대로, "
        "모두 같은 무게로 한 줄씩 채운다(지나간 학기는 넣지 않는다 — 서버가 회고 자리로 "
        "채운다. 이번 학기라고 과목·활동·주제를 붙이지 않는다). 저장하면 화면에 흐름 카드가 뜨고, "
        "학생이 카드의 확정 버튼을 눌러야 다음 단계로 넘어간다. 학생이 흐름을 고치자고 "
        "하면 반영해서 다시 호출하라(다시 호출하면 확정이 풀린다).",
        {
            "career_track": {"type": "string", "description": "흐름이 향하는 진로 축"},
            "destination": {
                "type": "string",
                "description": (
                    "학생과 합의한 도착점 — 3학년을 마칠 때 입시에서 이 학생이 어떤 "
                    "학생으로 읽히면 좋을지 한 문장"
                ),
            },
            "focus": {"type": "string", "description": "3년을 관통하는 핵심 관심 한 줄"},
            "so_far": {
                "type": "string",
                "description": (
                    "지나간 학기의 실제 기록에서 읽은 출발점 1~2문장. 기록이 없거나 "
                    "학생부가 반영되지 않았으면 빈 문자열."
                ),
            },
            "nodes": {"type": "array", "items": _FLOW_NODE_SCHEMA},
        },
        ["career_track", "destination", "focus", "nodes"],
    ),
    _tool(
        "set_semester_goal",
        "[2단계] 확정된 3개년 흐름 안에서 학생과 합의한 **이번 학기 목표**를 저장한다. "
        "흐름이 확정되기 전에는 거부된다. 목표가 바뀌면 다시 호출하라(이미 정리한 주제 "
        "초안은 새 목표에 맞춰 다시 만들어야 한다).",
        {
            "title": {"type": "string"},
            "objective": {"type": "string"},
            "candidate_subjects": {"type": "array", "items": {"type": "string"}},
            "competency_goals": {"type": "array", "items": {"type": "string"}},
        },
        ["title", "objective"],
    ),
    _tool(
        "propose_draft_plan",
        "[3단계] 이번 학기 목표에서 나온 구체 탐구 주제를 초안으로 저장한다(아직 확정 "
        "아님). 이번 학기 목표가 저장된 뒤에만 쓸 수 있다. plan_events는 정확히 10개"
        "(core 4 + optional 6)이며, 대화에서 학생과 함께 고른 주제를 core 앞쪽에 둔다. "
        "3개년 흐름과 이번 학기 목표는 이미 저장된 것을 서버가 그대로 쓴다. 학생이 "
        "반려하면 다시 호출해 덮어써라.",
        {"plan_events": {"type": "array", "items": _PLAN_EVENT_SCHEMA}},
        ["plan_events"],
    ),
    _tool(
        "propose_full_replan_exception",
        "재평가 상담에서만 쓴다. 학생의 상황(진로 전환 등)이 기존 3개년 큰 계획의 "
        "전제 자체를 무너뜨렸다고 판단될 때만, 처음부터 다시 세우자고 제안한다. "
        "이 호출만으로는 아무것도 바뀌지 않는다 — 학생이 화면의 별도 확인 버튼을 "
        "눌러야 실제로 전체 재설계가 허용되고, 그 뒤 3개년 흐름부터 다시 조율한다.",
        {"rationale": {"type": "string", "description": "왜 전체를 다시 세워야 하는지"}},
        ["rationale"],
    ),
    _tool(
        "signal_ready_to_conclude",
        "[4단계] 상담이 충분히 마무리됐다고 판단되면 호출한다. propose_draft_plan으로 "
        "주제 초안을 저장한 뒤, 학생이 정리한 내용에 동의했을 때만 호출한다. 이후 학생이 "
        "화면의 '상담 마치고 메인 화면으로' 버튼을 눌러야 실제로 확정된다 — 대화가 "
        "이어지면 이 신호는 취소되니, 정말 끝났을 때만 불러라.",
        {"summary": {"type": "string", "description": "무엇을 정했는지 한두 문장 요약"}},
        ["summary"],
    ),
]

def tools_for_stage(session: ConsultationSession) -> list[dict[str, Any]]:
    """이번 턴에 챗봇에게 보여 줄 도구 — 지금 단계와 그 앞 단계를 고치는 도구만.

    모든 도구를 늘 보여 주면 흐름 단계에서도 모델이 "이번 학기 주제 10개 저장" 도구
    설명을 매 턴 읽고, 그쪽으로 대화를 끌고 가는 것이 실제로 관측됐다. 핸들러가 순서를
    어긴 호출을 거부하긴 하지만, 애초에 다음 단계 수단을 보여 주지 않는 편이 대화
    자체가 순서를 지키게 만든다. 도구 목록은 턴마다 한 번 정한다 — 한 턴 안에서 목표를
    저장하자마자 주제까지 저장하거나, 주제를 저장하자마자 마무리 신호를 보내 학생의
    반응을 건너뛰는 것을 막기 위해서다.
    """
    stage = session_stage(session)
    if stage == STAGE_FLOW:
        names = ["propose_three_year_flow"]
    elif stage == STAGE_SEMESTER_GOAL:
        names = ["set_semester_goal"]
    elif stage == STAGE_TOPICS:
        names = ["propose_draft_plan", "set_semester_goal"]
    else:  # wrap_up
        names = ["signal_ready_to_conclude", "propose_draft_plan", "set_semester_goal"]

    flow_needed = needs_flow(session.kind, session.full_replan_confirmed_at is not None)
    if stage != STAGE_FLOW and flow_needed:
        # 흐름을 확정한 뒤에도 학생이 흐름을 고치고 싶어 하면 다시 제안할 수 있다(확정이 풀림).
        names.append("propose_three_year_flow")
    if session.kind == ConsultationKind.SEMESTER_REVIEW.value and not flow_needed:
        names.append("propose_full_replan_exception")
    by_name = {spec["function"]["name"]: spec for spec in TOOL_SPECS}
    return [by_name[name] for name in names]


TOOL_HANDLERS = {
    "propose_three_year_flow": _propose_three_year_flow,
    "set_semester_goal": _set_semester_goal,
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


# ── 졸업생(수시 재수생) 적합성 상담 전용 도구 ──────────────────────────────
# 재학생 로드맵 도구(위)와 완전히 분리한다. 졸업생 상담은 계획을 만들지 않고,
# 대신 목표 학과의 공개 입시 데이터를 조회해 승산을 근거 있게 말한다.


async def _lookup_department_fit(
    db: AsyncSession, user: User, session: ConsultationSession, args: dict[str, Any]
) -> dict[str, Any]:
    department = args.get("department", "")
    if not department or not str(department).strip():
        return {"error": "department(조회할 학과 이름)를 채워주세요"}
    return await admission_fit_service.search_program_fit(
        db,
        department_query=str(department),
        university_query=(str(args["university"]) if args.get("university") else None),
    )


GRADUATE_FIT_TOOL_SPECS: list[dict[str, Any]] = [
    _tool(
        "lookup_department_fit",
        "목표 학과의 공개 입시 데이터(모집인원·수시/정시 경쟁률·전형별 결과·교육목표·"
        "진로)를 어디가 자료에서 찾아 온다. 학생이 지망하는 학과의 현실적 승산을 감이 "
        "아니라 실제 수치로 판단하기 위해 쓴다. 대학이 특정되면 university도 함께 넘겨 "
        "좁혀라. 결과가 비어 있으면 데이터가 없다는 뜻이니 수치를 지어내지 마라.",
        {
            "department": {"type": "string", "description": "조회할 학과 이름(예: 컴퓨터공학과)"},
            "university": {
                "type": "string",
                "description": "특정 대학으로 좁힐 때만. 모르면 비워 둔다.",
            },
        },
        ["department"],
    ),
]

_GRADUATE_FIT_HANDLERS = {
    "lookup_department_fit": _lookup_department_fit,
}


async def execute_graduate_fit_tool(
    db: AsyncSession,
    user: User,
    session: ConsultationSession,
    name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    handler = _GRADUATE_FIT_HANDLERS.get(name)
    if handler is None:
        return {"error": f"알 수 없는 도구입니다: {name}"}
    try:
        return await handler(db, user, session, args)
    except AppError as exc:
        return {"error": exc.message}
    except Exception as exc:
        await db.rollback()
        return {"error": f"{type(exc).__name__}: {exc}"}
