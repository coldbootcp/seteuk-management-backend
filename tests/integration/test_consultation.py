"""진단+상담 필수 관문 — 게이트 판정, 상담 대화의 도구 호출, 확정(conclude)까지."""

import json
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.services.chat_service as chat_service
from app.core.dependencies import require_consultation_satisfied
from app.main import app
from app.models.conversation import Conversation
from tests.conftest import TestSessionLocal, _bypass_consultation_gate


@pytest.fixture(autouse=True)
def _use_real_gate():
    """이 파일은 관문 자체를 검증하므로, 다른 통합 테스트를 위한 전역 우회를
    이 파일 안에서만 걷어낸다."""
    app.dependency_overrides.pop(require_consultation_satisfied, None)
    yield
    app.dependency_overrides[require_consultation_satisfied] = _bypass_consultation_gate


@pytest.fixture(autouse=True)
def _patch_session_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_service, "AsyncSessionLocal", TestSessionLocal)

    async def no_suggestions(_text: str) -> list[str]:
        return []

    # 추천 답변 칩은 별도 LLM 호출이라 이 파일의 관심사가 아니다.
    monkeypatch.setattr(chat_service, "_generate_suggested_replies", no_suggestions)


def _chunk(content: str | None = None, tool_calls: list[Any] | None = None) -> SimpleNamespace:
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _tool_call_delta(index: int, call_id: str, name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(
        index=index, id=call_id, function=SimpleNamespace(name=name, arguments=arguments)
    )


def _install_stream(monkeypatch: pytest.MonkeyPatch, rounds: list[list[SimpleNamespace]]) -> None:
    remaining = list(rounds)

    async def fake_stream_chat(messages, tools=None):
        chunks = remaining.pop(0) if remaining else [_chunk("")]
        for chunk in chunks:
            yield chunk

    monkeypatch.setattr(chat_service, "stream_chat", fake_stream_chat)


def _parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in body.strip().split("\n\n"):
        if not block.strip():
            continue
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def _onboard(client: AsyncClient, headers: dict[str, str], grade: int, semester: int) -> None:
    await client.post(
        "/api/v1/profile",
        json={
            "name": "홍길동",
            "grade": grade,
            "semester": semester,
            "career_goal": {"goal": "데이터 기반 연구직"},
            "target_department": "통계학과",
            "interest_keywords": ["데이터 분석"],
            "career_specificity": {"level": "specific"},
            "preferred_output_types": ["report"],
            "activity_channels": ["동아리"],
            "self_assessed_strengths": "수학에 강함",
            "self_assessed_weaknesses": "독서가 부족함",
        },
        headers=headers,
    )


def _flow_nodes(from_grade: int = 1, from_semester: int = 1) -> list[dict[str, Any]]:
    stages = [
        (1, 1, "탐색"), (1, 2, "기초"), (2, 1, "연결"),
        (2, 2, "분화"), (3, 1, "독립 탐구"), (3, 2, "종합"),
    ]
    start = (from_grade - 1) * 2 + (from_semester - 1)
    return [
        {
            "grade": grade,
            "semester": semester,
            "narrative_stage": stage,
            "title": f"{stage} 단계 방향",
            "objective": f"{stage} 단계 방향 설명",
            "candidate_subjects": ["수학"],
            "competency_goals": ["탐구 설계"],
        }
        for grade, semester, stage in stages[start:]
    ]


def _flow_args(from_grade: int = 1, from_semester: int = 1) -> dict[str, Any]:
    return {
        "career_track": "데이터 사이언티스트",
        "destination": "공공 데이터로 지역 문제를 분석한 탐구 보고서",
        "focus": "데이터로 사회 현상 설명하기",
        "so_far": "",
        "nodes": _flow_nodes(from_grade, from_semester),
    }


_GOAL_ARGS = {
    "title": "이번 학기 목표",
    "objective": "관심 분야와 교과의 첫 연결을 찾습니다.",
    "candidate_subjects": ["통합과학"],
    "competency_goals": ["진로 탐색"],
}


def _ten_events() -> list[dict[str, Any]]:
    events = []
    for i in range(10):
        events.append(
            {
                "order_index": i,
                "month_day": "04-15",
                "category": "활동",
                "subject": "수학",
                "priority": "core" if i < 4 else "optional",
                "title": f"탐구 주제 {i + 1}",
                "description": f"탐구 주제 {i + 1} 설명",
            }
        )
    return events


def _tool_call_chunk(name: str, args: dict[str, Any]) -> SimpleNamespace:
    return _chunk(
        tool_calls=[_tool_call_delta(0, "call_1", name, json.dumps(args, ensure_ascii=False))]
    )


async def _turn(
    client: AsyncClient,
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
    tool: str | None,
    args: dict[str, Any] | None = None,
    content: str = "네",
) -> list[tuple[str, dict[str, Any]]]:
    """대화 한 턴. 각 턴마다 쓸 라운드만 직전에 설치한다 — 도구 루프가 tool_calls가 빌
    때까지 stream_chat을 여러 번 부르므로, 미리 깔아 두면 앞 턴이 뒤 턴 것을 먹는다."""
    rounds = [[_tool_call_chunk(tool, args or {})]] if tool else [[_chunk("네, 좋아요.")]]
    _install_stream(monkeypatch, rounds)
    response = await client.post(
        f"/api/v1/consultation/sessions/{session_id}/messages",
        json={"content": content},
        headers=headers,
    )
    return _parse_sse(response.text)


def _action(events: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    return next(p for e, p in events if e == "action")


def _signal(events: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    return next(p for e, p in events if e == "signal")


async def _run_initial_consultation(
    client: AsyncClient,
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
    from_grade: int = 1,
    from_semester: int = 1,
) -> None:
    await _turn(
        client, headers, monkeypatch, session_id,
        "propose_three_year_flow", _flow_args(from_grade, from_semester),
    )
    await client.post(
        f"/api/v1/consultation/sessions/{session_id}/confirm-flow",
        json={"confirmed": True},
        headers=headers,
    )
    await _turn(client, headers, monkeypatch, session_id, "set_semester_goal", _GOAL_ARGS)
    await _turn(
        client, headers, monkeypatch, session_id,
        "propose_draft_plan", {"plan_events": _ten_events()},
    )
    await _turn(
        client, headers, monkeypatch, session_id,
        "signal_ready_to_conclude", {"summary": "완료"},
    )


async def test_gate_blocks_new_user_until_initial_consultation(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _onboard(client, auth_headers, grade=1, semester=1)

    status = await client.get("/api/v1/consultation/status", headers=auth_headers)
    assert status.json() == {
        "satisfied": False,
        "required_kind": "initial",
        "target_grade": 1,
        "target_semester": 1,
        "resumable_session_id": None,
    }

    blocked = await client.post("/api/v1/roadmaps", json={}, headers=auth_headers)
    assert blocked.status_code == 403
    body = blocked.json()
    assert body["error_code"] == "CONSULTATION_REQUIRED"
    assert body["required_kind"] == "initial"


async def test_initial_consultation_walks_flow_goal_topics_then_concludes(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _onboard(client, auth_headers, grade=1, semester=1)

    session = (
        await client.post("/api/v1/consultation/sessions", headers=auth_headers)
    ).json()
    sid = session["id"]
    assert session["kind"] == "initial"
    assert session["status"] == "in_progress"
    assert session["stage"] == "flow"

    # [1단계] 흐름이 없으면 학기 목표·주제 저장이 모두 거부된다.
    early_goal = await _turn(
        client, auth_headers, monkeypatch, sid, "set_semester_goal", _GOAL_ARGS
    )
    assert "error" in _action(early_goal)["result"]
    early_plan = await _turn(
        client, auth_headers, monkeypatch, sid,
        "propose_draft_plan", {"plan_events": _ten_events()},
    )
    assert "error" in _action(early_plan)["result"]

    flow = await _turn(
        client, auth_headers, monkeypatch, sid, "propose_three_year_flow", _flow_args()
    )
    assert _action(flow)["result"]["stored"] is True
    signal = _signal(flow)
    assert signal["stage"] == "flow"
    assert signal["flow_confirmed"] is False
    assert len(signal["flow"]["nodes"]) == 6
    # 흐름은 3학년 말 도착점과 함께 저장돼 카드에 그대로 보인다.
    assert signal["flow"]["destination"] == "공공 데이터로 지역 문제를 분석한 탐구 보고서"

    # 말로 동의해도 흐름이 확정되지 않는다 — 버튼(confirm-flow)만 확정한다.
    still_flow = await _turn(
        client, auth_headers, monkeypatch, sid, "set_semester_goal", _GOAL_ARGS
    )
    assert "error" in _action(still_flow)["result"]

    confirmed = await client.post(
        f"/api/v1/consultation/sessions/{sid}/confirm-flow",
        json={"confirmed": True},
        headers=auth_headers,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["stage"] == "semester_goal"
    assert confirmed.json()["flow_confirmed"] is True

    # [2단계] 목표가 없으면 주제 저장이 거부된다.
    no_goal_plan = await _turn(
        client, auth_headers, monkeypatch, sid,
        "propose_draft_plan", {"plan_events": _ten_events()},
    )
    assert "error" in _action(no_goal_plan)["result"]

    goal = await _turn(client, auth_headers, monkeypatch, sid, "set_semester_goal", _GOAL_ARGS)
    assert _action(goal)["result"]["stored"] is True
    assert _signal(goal)["stage"] == "topics"

    # [3단계] 주제 초안 저장
    plan = await _turn(
        client, auth_headers, monkeypatch, sid,
        "propose_draft_plan", {"plan_events": _ten_events()},
    )
    assert _action(plan)["result"]["stored"] is True
    assert _signal(plan)["stage"] == "wrap_up"
    assert _signal(plan)["ready"] is False

    ready = await _turn(
        client, auth_headers, monkeypatch, sid,
        "signal_ready_to_conclude", {"summary": "계획을 정리했습니다."},
    )
    assert _signal(ready)["ready"] is True

    concluded = await client.post(
        f"/api/v1/consultation/sessions/{sid}/conclude", headers=auth_headers
    )
    assert concluded.status_code == 200
    assert concluded.json()["status"] == "concluded"

    status = await client.get("/api/v1/consultation/status", headers=auth_headers)
    assert status.json()["satisfied"] is True

    roadmap = await client.get("/api/v1/roadmaps/active", headers=auth_headers)
    body = roadmap.json()
    assert [n["narrative_stage"] for n in body["nodes"]] == [
        "탐색", "기초", "연결", "분화", "독립 탐구", "종합"
    ]
    # 이번 학기 마디는 합의한 목표, 미래 마디는 확정한 3개년 흐름 그대로다.
    active_node = next(n for n in body["nodes"] if n["is_current"])
    assert active_node["title"] == "이번 학기 목표"
    assert len(active_node["plan_events"]) == 10
    assert body["nodes"][5]["title"] == "종합 단계 방향"

    conversations = await client.get("/api/v1/conversations", headers=auth_headers)
    consultation_conv = next(
        c for c in conversations.json()["items"] if c["purpose"] == "initial_consultation"
    )
    assert consultation_conv["title"] == "3개년 흐름 설계"
    assert consultation_conv["title_source"] == "default"


async def test_flow_only_covers_remaining_semesters_and_changes_reset_confirmation(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _onboard(client, auth_headers, grade=2, semester=2)
    sid = (await client.post("/api/v1/consultation/sessions", headers=auth_headers)).json()["id"]

    # 남은 학기(2-2, 3-1, 3-2)가 빠지면 거부된다.
    partial = _flow_args(3, 1)
    missing = await _turn(
        client, auth_headers, monkeypatch, sid, "propose_three_year_flow", partial
    )
    assert "2학년 2학기" in _action(missing)["result"]["error"]

    # 지나간 학기를 같이 보내도 저장되는 것은 남은 학기뿐이다.
    stored = await _turn(
        client, auth_headers, monkeypatch, sid, "propose_three_year_flow", _flow_args(1, 1)
    )
    nodes = _signal(stored)["flow"]["nodes"]
    assert [(n["grade"], n["semester"]) for n in nodes] == [(2, 2), (3, 1), (3, 2)]

    await client.post(
        f"/api/v1/consultation/sessions/{sid}/confirm-flow",
        json={"confirmed": True},
        headers=auth_headers,
    )
    await _turn(client, auth_headers, monkeypatch, sid, "set_semester_goal", _GOAL_ARGS)

    # 흐름을 고치면 확정과 그 위에 쌓은 학기 목표가 풀린다.
    changed = _flow_args(2, 2)
    changed["nodes"][1]["title"] = "바뀐 3학년 1학기 방향"
    after = await _turn(client, auth_headers, monkeypatch, sid, "propose_three_year_flow", changed)
    sig = _signal(after)
    assert sig["stage"] == "flow"
    assert sig["flow_confirmed"] is False
    assert sig["semester_goal"] is None

    # 같은 흐름을 다시 보내는 것만으로는 확정이 풀리지 않는다.
    await client.post(
        f"/api/v1/consultation/sessions/{sid}/confirm-flow",
        json={"confirmed": True},
        headers=auth_headers,
    )
    same = await _turn(client, auth_headers, monkeypatch, sid, "propose_three_year_flow", changed)
    assert _signal(same)["flow_confirmed"] is True


async def test_confirm_flow_requires_a_proposed_flow(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _onboard(client, auth_headers, grade=1, semester=1)
    sid = (await client.post("/api/v1/consultation/sessions", headers=auth_headers)).json()["id"]
    response = await client.post(
        f"/api/v1/consultation/sessions/{sid}/confirm-flow",
        json={"confirmed": True},
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "CONSULTATION_NOT_READY"


async def test_readiness_is_revoked_when_conversation_continues(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _onboard(client, auth_headers, grade=1, semester=1)
    sid = (await client.post("/api/v1/consultation/sessions", headers=auth_headers)).json()["id"]
    await _run_initial_consultation(client, auth_headers, monkeypatch, sid)

    status = await client.get(f"/api/v1/consultation/sessions/{sid}", headers=auth_headers)
    assert status.json()["ready"] is True

    followup = await _turn(
        client, auth_headers, monkeypatch, sid, None, content="질문이 하나 더 있어요."
    )
    assert _signal(followup)["ready"] is False


async def test_semester_review_keeps_flow_and_full_replan_restarts_from_flow(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # 최초 상담을 먼저 끝내 로드맵을 만들어 둔다.
    await _onboard(client, auth_headers, grade=1, semester=1)
    initial = (await client.post("/api/v1/consultation/sessions", headers=auth_headers)).json()
    await _run_initial_consultation(client, auth_headers, monkeypatch, initial["id"])
    await client.post(
        f"/api/v1/consultation/sessions/{initial['id']}/conclude", headers=auth_headers
    )

    # 학기를 올려 재평가를 강제한다. 재평가는 기존 흐름을 유지하므로 목표부터 시작한다.
    await _onboard(client, auth_headers, grade=1, semester=2)
    review = (await client.post("/api/v1/consultation/sessions", headers=auth_headers)).json()
    rid = review["id"]
    assert review["kind"] == "semester_review"
    assert review["stage"] == "semester_goal"

    # 동의 없이 흐름을 새로 세우려 하면 거부된다.
    rejected = await _turn(
        client, auth_headers, monkeypatch, rid, "propose_three_year_flow", _flow_args(1, 2)
    )
    assert "error" in _action(rejected)["result"]

    # 이번 학기만 고치는 기본 경로는 그대로 동작한다.
    goal = await _turn(client, auth_headers, monkeypatch, rid, "set_semester_goal", _GOAL_ARGS)
    assert _signal(goal)["stage"] == "topics"

    # 명시적으로 동의하면 3개년 흐름부터 다시 세운다 — 앞서 정한 목표는 풀린다.
    confirmed = await client.post(
        f"/api/v1/consultation/sessions/{rid}/confirm-full-replan",
        json={"confirmed": True},
        headers=auth_headers,
    )
    assert confirmed.json()["stage"] == "flow"
    assert confirmed.json()["semester_goal"] is None

    allowed = await _turn(
        client, auth_headers, monkeypatch, rid, "propose_three_year_flow", _flow_args(1, 2)
    )
    assert _action(allowed)["result"].get("stored") is True
    assert len(_signal(allowed)["flow"]["nodes"]) == 5


async def test_semester_review_conversation_gets_period_title(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _onboard(client, auth_headers, grade=1, semester=1)
    initial = (await client.post("/api/v1/consultation/sessions", headers=auth_headers)).json()
    await _run_initial_consultation(client, auth_headers, monkeypatch, initial["id"])
    await client.post(
        f"/api/v1/consultation/sessions/{initial['id']}/conclude", headers=auth_headers
    )
    await _onboard(client, auth_headers, grade=1, semester=2)
    await client.post("/api/v1/consultation/sessions", headers=auth_headers)

    async with TestSessionLocal() as db:
        titles = {
            c.purpose: c.title for c in (await db.scalars(select(Conversation))).all()
        }
    assert titles["semester_review_consultation"] == "1학년 2학기 점검"
