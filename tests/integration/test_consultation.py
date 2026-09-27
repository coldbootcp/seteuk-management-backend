"""진단+상담 필수 관문 — 게이트 판정, 상담 대화의 도구 호출, 확정(conclude)까지."""

import json
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient

import app.services.chat_service as chat_service
from app.core.dependencies import require_consultation_satisfied
from app.main import app
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


def _six_nodes() -> list[dict[str, Any]]:
    stages = [
        (1, 1, "탐색"), (1, 2, "기초"), (2, 1, "연결"),
        (2, 2, "분화"), (3, 1, "독립 탐구"), (3, 2, "종합"),
    ]
    return [
        {
            "grade": grade,
            "semester": semester,
            "narrative_stage": stage,
            "title": f"{stage} 단계 목표",
            "objective": f"{stage} 단계 목표 설명",
            "candidate_subjects": ["수학"],
            "competency_goals": ["탐구 설계"],
        }
        for grade, semester, stage in stages
    ]


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


async def test_opening_turn_is_model_generated_and_persisted(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """학생이 아무 말도 하기 전, 화면이 고정 문구 대신 모델이 직접 지은 여는 말을
    보여준다는 계약 — 스트리밍으로 나가고, 대화 기록에도 assistant 메시지로 남는다."""
    await _onboard(client, auth_headers, grade=1, semester=1)
    session = (
        await client.post("/api/v1/consultation/sessions", headers=auth_headers)
    ).json()

    before = await client.get(
        f"/api/v1/consultation/sessions/{session['id']}/messages", headers=auth_headers
    )
    assert before.json() == []

    _install_stream(monkeypatch, [[_chunk("안녕하세요! 요즘 관심 있는 분야가 있나요?")]])

    response = await client.post(
        f"/api/v1/consultation/sessions/{session['id']}/opening", headers=auth_headers
    )
    events = _parse_sse(response.text)
    token = next(p for e, p in events if e == "token")
    assert "안녕하세요" in token["delta"]
    done = next(p for e, p in events if e == "done")
    assert done["message_id"] is not None

    after = await client.get(
        f"/api/v1/consultation/sessions/{session['id']}/messages", headers=auth_headers
    )
    messages = after.json()
    assert len(messages) == 1
    assert messages[0]["role"] == "assistant"
    assert "안녕하세요" in messages[0]["content"]


async def test_opening_turn_rejected_once_conversation_has_started(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """이미 메시지가 있는 세션(재개하는 상담)에서는 여는 말을 다시 짓지 않는다 —
    화면이 잘못 두 번 부르더라도 서버가 방어한다."""
    await _onboard(client, auth_headers, grade=1, semester=1)
    session = (
        await client.post("/api/v1/consultation/sessions", headers=auth_headers)
    ).json()

    _install_stream(monkeypatch, [[_chunk("안녕하세요!")]])
    await client.post(
        f"/api/v1/consultation/sessions/{session['id']}/opening", headers=auth_headers
    )

    second = await client.post(
        f"/api/v1/consultation/sessions/{session['id']}/opening", headers=auth_headers
    )
    events = _parse_sse(second.text)
    error = next(p for e, p in events if e == "error")
    assert error["error_code"] == "CONSULTATION_ALREADY_STARTED"

    messages = (
        await client.get(
            f"/api/v1/consultation/sessions/{session['id']}/messages", headers=auth_headers
        )
    ).json()
    assert len(messages) == 1


async def test_initial_consultation_conclude_creates_roadmap_and_opens_gate(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _onboard(client, auth_headers, grade=1, semester=1)

    session = (
        await client.post("/api/v1/consultation/sessions", headers=auth_headers)
    ).json()
    assert session["kind"] == "initial"
    assert session["status"] == "in_progress"

    draft_args = {
        "mode": "full_replan",
        "career_track": "데이터 사이언티스트",
        "focus": "데이터 분석",
        "nodes": _six_nodes(),
        "current_node": {
            "title": "1학년 1학기 목표",
            "objective": "관심 분야와 교과의 첫 연결을 찾습니다.",
            "candidate_subjects": ["통합과학"],
            "competency_goals": ["진로 탐색"],
        },
        "plan_events": _ten_events(),
    }
    # 각 HTTP 요청(대화 한 턴)마다 도구 루프가 tool_calls가 빌 때까지 stream_chat을
    # 여러 라운드 부를 수 있으므로, 한 턴에 쓸 라운드만 그 턴 직전에 새로 설치한다 —
    # 그렇지 않으면 뒤 턴에 쓰려던 라운드를 앞 턴이 먼저 소비해 버린다.
    _install_stream(monkeypatch, [[_tool_call_chunk("propose_draft_plan", draft_args)]])

    r1 = await client.post(
        f"/api/v1/consultation/sessions/{session['id']}/messages",
        json={"content": "저는 데이터 분석에 관심이 많아요."},
        headers=auth_headers,
    )
    events1 = _parse_sse(r1.text)
    assert next(p for e, p in events1 if e == "signal")["ready"] is False
    action1 = next(p for e, p in events1 if e == "action")
    assert action1["result"]["stored"] is True

    _install_stream(
        monkeypatch,
        [[_tool_call_chunk("signal_ready_to_conclude", {"summary": "계획을 확정했습니다."})]],
    )
    r2 = await client.post(
        f"/api/v1/consultation/sessions/{session['id']}/messages",
        json={"content": "네 좋아요, 그렇게 진행해주세요."},
        headers=auth_headers,
    )
    events2 = _parse_sse(r2.text)
    signal2 = next(p for e, p in events2 if e == "signal")
    assert signal2["ready"] is True

    concluded = await client.post(
        f"/api/v1/consultation/sessions/{session['id']}/conclude", headers=auth_headers
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
    active_node = next(n for n in body["nodes"] if n["is_current"])
    assert active_node["title"] == "1학년 1학기 목표"
    assert len(active_node["plan_events"]) == 10


async def test_readiness_is_revoked_when_conversation_continues(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _onboard(client, auth_headers, grade=1, semester=1)
    session = (
        await client.post("/api/v1/consultation/sessions", headers=auth_headers)
    ).json()

    draft_args = {
        "mode": "full_replan",
        "career_track": "데이터 사이언티스트",
        "focus": "데이터 분석",
        "nodes": _six_nodes(),
        "current_node": {"title": "목표", "objective": "설명"},
        "plan_events": _ten_events(),
    }
    _install_stream(monkeypatch, [[_tool_call_chunk("propose_draft_plan", draft_args)]])
    await client.post(
        f"/api/v1/consultation/sessions/{session['id']}/messages",
        json={"content": "계획을 세워주세요."},
        headers=auth_headers,
    )
    _install_stream(
        monkeypatch, [[_tool_call_chunk("signal_ready_to_conclude", {"summary": "완료"})]]
    )
    ready = await client.post(
        f"/api/v1/consultation/sessions/{session['id']}/messages",
        json={"content": "좋아요."},
        headers=auth_headers,
    )
    assert next(p for e, p in _parse_sse(ready.text) if e == "signal")["ready"] is True

    _install_stream(monkeypatch, [[_chunk("잠깐, 하나만 더 물어볼게요.")]])
    followup = await client.post(
        f"/api/v1/consultation/sessions/{session['id']}/messages",
        json={"content": "질문이 하나 더 있어요."},
        headers=auth_headers,
    )
    assert next(p for e, p in _parse_sse(followup.text) if e == "signal")["ready"] is False


async def test_semester_review_full_replan_requires_explicit_confirmation(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # 최초 상담을 먼저 끝내 로드맵을 만들어 둔다.
    await _onboard(client, auth_headers, grade=1, semester=1)
    initial = (
        await client.post("/api/v1/consultation/sessions", headers=auth_headers)
    ).json()
    draft_args = {
        "mode": "full_replan",
        "career_track": "데이터 사이언티스트",
        "focus": "데이터 분석",
        "nodes": _six_nodes(),
        "current_node": {"title": "목표", "objective": "설명"},
        "plan_events": _ten_events(),
    }
    _install_stream(monkeypatch, [[_tool_call_chunk("propose_draft_plan", draft_args)]])
    await client.post(
        f"/api/v1/consultation/sessions/{initial['id']}/messages",
        json={"content": "계획을 세워주세요."},
        headers=auth_headers,
    )
    _install_stream(
        monkeypatch, [[_tool_call_chunk("signal_ready_to_conclude", {"summary": "완료"})]]
    )
    await client.post(
        f"/api/v1/consultation/sessions/{initial['id']}/messages",
        json={"content": "좋아요."},
        headers=auth_headers,
    )
    await client.post(
        f"/api/v1/consultation/sessions/{initial['id']}/conclude", headers=auth_headers
    )

    # 학기를 올려 재평가를 강제한다.
    await _onboard(client, auth_headers, grade=1, semester=2)
    review = (
        await client.post("/api/v1/consultation/sessions", headers=auth_headers)
    ).json()
    assert review["kind"] == "semester_review"

    # 동의 없이 전체 재설계를 시도하면 거부된다.
    _install_stream(monkeypatch, [[_tool_call_chunk("propose_draft_plan", draft_args)]])
    rejected = await client.post(
        f"/api/v1/consultation/sessions/{review['id']}/messages",
        json={"content": "진로가 완전히 바뀌었어요."},
        headers=auth_headers,
    )
    action = next(p for e, p in _parse_sse(rejected.text) if e == "action")
    assert "error" in action["result"]

    # 명시적으로 동의하면 이후에는 허용된다.
    await client.post(
        f"/api/v1/consultation/sessions/{review['id']}/confirm-full-replan",
        json={"confirmed": True},
        headers=auth_headers,
    )
    _install_stream(monkeypatch, [[_tool_call_chunk("propose_draft_plan", draft_args)]])
    allowed = await client.post(
        f"/api/v1/consultation/sessions/{review['id']}/messages",
        json={"content": "그럼 처음부터 다시 세워주세요."},
        headers=auth_headers,
    )
    action2 = next(p for e, p in _parse_sse(allowed.text) if e == "action")
    assert action2["result"].get("stored") is True


def _tool_call_chunk(name: str, args: dict[str, Any]) -> SimpleNamespace:
    return _chunk(
        tool_calls=[_tool_call_delta(0, "call_1", name, json.dumps(args, ensure_ascii=False))]
    )


def test_initial_consultation_prompt_and_tools_enforce_concrete_roadmap() -> None:
    """최초 상담 프롬프트와 도구 명세가 추상적 로드맵을 금지하고
    구체적 학술 서사 3단계 빌드업과 구조화 포맷을 강제하는지 검증."""
    from app.services.chat.consultation_prompts import (
        build_consultation_system_prompt,
    )
    from app.services.chat.consultation_tools import TOOL_SPECS

    prompt = build_consultation_system_prompt(
        "initial", context_json="{}", roadmap_summary_json=None
    )

    # 1. 낡고 추상적인 구태의연한 예시가 제거되었는지 검증
    assert "기초 탐색 → 구체화 → 심화·확장" not in prompt

    # 2. 추상적 수식어 금지 규칙 포함 검증
    assert "추상적 수식어" in prompt
    assert "알맹이 없는" in prompt
    assert "인과 사슬(Narrative Arc)" in prompt

    # 3. 학술 서사 3단계 빌드업 원칙 포함 검증
    assert "1학년 (개념 탐색 & 원리 발견)" in prompt
    assert "2학년 (교과 융합 & 공학적/학술적 모델링)" in prompt
    assert "3학년 (독립 심화 & 최신 쟁점/한계 극복)" in prompt

    # 4. 대화 내 구조화 포맷 강제 검증
    assert "[3개년 학술 로드맵 큰 그림]" in prompt
    assert "[구체적 학술 주제명] (연계교과)" in prompt

    # 5. propose_draft_plan 도구의 nodes 명세에 구체적 테마/목적 지침 포함 검증
    propose_tool = next(t for t in TOOL_SPECS if t["function"]["name"] == "propose_draft_plan")
    nodes_schema = propose_tool["function"]["parameters"]["properties"]["nodes"]
    node_props = nodes_schema["items"]["properties"]
    assert "구체적 학술 연구 테마" in node_props["title"]["description"]
    assert "교과목 개념 연계" in node_props["objective"]["description"]

