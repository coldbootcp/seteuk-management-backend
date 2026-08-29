import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient

import app.services.chat_service as chat_service
from tests.conftest import TestSessionLocal


def _chunk(content: str | None = None, tool_calls: list[Any] | None = None) -> SimpleNamespace:
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _tool_call_delta(index: int, call_id: str, name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


CALLS: list[dict[str, Any]] = []


@pytest.fixture(autouse=True)
def _patch_session_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_service, "AsyncSessionLocal", TestSessionLocal)
    CALLS.clear()


def _install_stream(monkeypatch: pytest.MonkeyPatch, rounds: list[list[SimpleNamespace]]) -> None:
    """LLM이 라운드마다 내보낼 청크 목록을 순서대로 재생한다."""
    remaining = list(rounds)

    async def fake_stream_chat(messages, tools=None) -> AsyncIterator[SimpleNamespace]:
        CALLS.append({"messages": messages, "tools": tools})
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


async def _new_conversation(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post("/api/v1/conversations", headers=headers)
    return response.json()["id"]


async def test_normal_mode_streams_tokens_and_persists_history(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stream(monkeypatch, [[_chunk("지금까지의 "), _chunk("활동을 보면요")]])
    conversation_id = await _new_conversation(client, auth_headers)

    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "제 활동 흐름 어때요?", "mode": "normal"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert [e for e, _ in events] == ["token", "token", "done"]
    assert events[-1][1]["applied_actions"] == []

    # 일반 모드에서는 도구를 아예 넘기지 않아 기록이 바뀔 수 없다.
    assert CALLS[0]["tools"] is None

    messages = await client.get(
        f"/api/v1/conversations/{conversation_id}/messages", headers=auth_headers
    )
    saved = messages.json()
    assert [m["role"] for m in saved] == ["user", "assistant"]
    assert saved[1]["content"] == "지금까지의 활동을 보면요"

    conversations = await client.get("/api/v1/conversations", headers=auth_headers)
    assert conversations.json()["items"][0]["title"] == "제 활동 흐름 어때요?"


async def test_edit_mode_executes_tool_and_records_actions(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stream(
        monkeypatch,
        [
            [
                _chunk(
                    tool_calls=[
                        _tool_call_delta(0, "call_1", "add_reading", '{"title": "이기적 유전자"'),
                        ]
                ),
                _chunk(tool_calls=[_tool_call_delta(0, "", "", ', "grade": 2}')]),
            ],
            [_chunk("독서 기록에 추가했어요.")],
        ],
    )
    conversation_id = await _new_conversation(client, auth_headers)

    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "이기적 유전자 읽었어요", "mode": "edit"},
        headers=auth_headers,
    )
    events = _parse_sse(response.text)
    kinds = [e for e, _ in events]
    assert kinds == ["action", "token", "done"]

    action = events[0][1]
    assert action["tool"] == "add_reading"
    # 인자가 여러 청크에 쪼개져 와도 하나로 합쳐져야 한다.
    assert action["arguments"] == {"title": "이기적 유전자", "grade": 2}
    assert "error" not in action["result"]

    readings = await client.get("/api/v1/reading-activities", headers=auth_headers)
    assert readings.json()["items"][0]["title"] == "이기적 유전자"

    messages = await client.get(
        f"/api/v1/conversations/{conversation_id}/messages", headers=auth_headers
    )
    assert messages.json()[1]["applied_actions"][0]["tool"] == "add_reading"


async def test_edit_mode_reports_tool_failure_instead_of_crashing(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stream(
        monkeypatch,
        [
            [
                _chunk(
                    tool_calls=[
                        _tool_call_delta(
                            0, "call_1", "update_plan", '{"plan_id": "not-a-uuid"}'
                        )
                    ]
                )
            ],
            [_chunk("그 계획을 찾지 못했어요.")],
        ],
    )
    conversation_id = await _new_conversation(client, auth_headers)

    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "그 계획 끝냈어요", "mode": "edit"},
        headers=auth_headers,
    )
    events = _parse_sse(response.text)
    assert events[0][0] == "action"
    assert "error" in events[0][1]["result"]
    # 실패해도 대화는 계속되고 답변이 저장된다.
    assert events[-1][0] == "done"


async def test_llm_failure_becomes_error_event(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_stream(messages, tools=None) -> AsyncIterator[SimpleNamespace]:
        raise RuntimeError("boom")
        yield  # pragma: no cover

    monkeypatch.setattr(chat_service, "stream_chat", failing_stream)
    conversation_id = await _new_conversation(client, auth_headers)

    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "안녕하세요", "mode": "normal"},
        headers=auth_headers,
    )
    events = _parse_sse(response.text)
    assert events == [
        ("error", {"error_code": "LLM_UNAVAILABLE", "message": "잠시 후 다시 시도해주세요"})
    ]

    # 실패해도 학생이 한 말은 남는다.
    messages = await client.get(
        f"/api/v1/conversations/{conversation_id}/messages", headers=auth_headers
    )
    assert [m["role"] for m in messages.json()] == ["user"]


async def test_conversation_is_scoped_to_owner(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stream(monkeypatch, [[_chunk("응답")]])
    conversation_id = await _new_conversation(client, auth_headers)

    signup = await client.post(
        "/api/v1/auth/signup",
        json={"email": "intruder@example.com", "password": "s3cure-passw0rd"},
    )
    other = {"Authorization": f"Bearer {signup.json()['access_token']}"}

    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "남의 대화", "mode": "edit"},
        headers=other,
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "CONVERSATION_NOT_FOUND"


async def test_chat_context_carries_the_students_own_records(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await client.post(
        "/api/v1/activities",
        json={
            "grade": 2,
            "semester": 1,
            "activity_category": "동아리활동",
            "activity_name": "AI 동아리 감염병 모델링",
            "activity_type": "project",
            "description": "SIR 모델을 구현했다.",
        },
        headers=auth_headers,
    )
    _install_stream(monkeypatch, [[_chunk("네")]])
    conversation_id = await _new_conversation(client, auth_headers)

    await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "제 활동 기억하세요?", "mode": "normal"},
        headers=auth_headers,
    )
    system_prompt = CALLS[0]["messages"][0]["content"]
    assert "AI 동아리 감염병 모델링" in system_prompt
    assert "<학생_데이터>" in system_prompt


async def test_text_before_and_after_a_tool_call_is_kept_separate(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """도구 실행 전에 흘린 말과 실행 후의 답변이 그대로 이어붙으면
    "…쌓였겠다!기록 완료했어."처럼 한 문장으로 읽힌다 — 실 DeepSeek 검증에서 발견."""
    _install_stream(
        monkeypatch,
        [
            [
                _chunk("기록할게요."),
                _chunk(
                    tool_calls=[
                        _tool_call_delta(0, "call_1", "add_reading", '{"title": "총, 균, 쇠"}')
                    ]
                ),
            ],
            [_chunk("독서 기록에 추가했어요.")],
        ],
    )
    conversation_id = await _new_conversation(client, auth_headers)

    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "총, 균, 쇠 읽었어요", "mode": "edit"},
        headers=auth_headers,
    )
    events = _parse_sse(response.text)
    streamed = "".join(data["delta"] for event, data in events if event == "token")
    assert streamed == "기록할게요.\n\n독서 기록에 추가했어요."

    messages = await client.get(
        f"/api/v1/conversations/{conversation_id}/messages", headers=auth_headers
    )
    # 저장된 본문도 스트리밍된 것과 같아야 한다.
    assert messages.json()[1]["content"] == streamed
