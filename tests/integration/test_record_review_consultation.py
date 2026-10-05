"""생기부 확인 상담(kind=record_review) — 멈춘 교체 업로드를 챗봇과 확인하고 버튼으로 반영한다."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.services.chat_service as chat_service
import app.services.seteuk_service as seteuk_service
from app.models.academic_performance import AcademicPerformance
from app.schemas.seteuk import SeteukAnalysisResult
from tests.conftest import TestSessionLocal
from tests.integration.test_consultation import (
    _chunk,
    _install_stream,
    _parse_sse,
    _tool_call_chunk,
)
from tests.integration.test_record_replace import _grade, _replace, _use_parse, _user_id
from tests.integration.test_seteuk_upload import _set_profile_grade


@pytest.fixture(autouse=True)
def _patch_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seteuk_service, "AsyncSessionLocal", TestSessionLocal)
    monkeypatch.setattr(chat_service, "AsyncSessionLocal", TestSessionLocal)

    async def no_suggestions(_text: str) -> list[str]:
        return []

    monkeypatch.setattr(chat_service, "_generate_suggested_replies", no_suggestions)


async def _stopped_upload(
    client: AsyncClient, headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """이름이 다르고(이상) 직접 입력한 성적과 다른(충돌) 생기부 — 반영하지 않고 멈춘다."""
    await _set_profile_grade(client, headers, grade=2, semester=1)
    user_id = await _user_id()
    async with TestSessionLocal() as db:
        db.add(
            AcademicPerformance(
                user_id=user_id, grade=1, semester=2, category="수학",
                subject="공통수학2", achievement_grade="A",
            )
        )
        await db.commit()
    _use_parse(
        monkeypatch,
        SeteukAnalysisResult(
            student_name="홍길 동",  # 공백만 다르면 같은 이름이다
            freshman_academic_year=2024,  # 계정과 다른 입학 연도(졸업 전) → 이상
            academic_performance=[_grade(1, 1, "공통수학1"), _grade(1, 2, "공통수학2", "B")],
        ),
    )
    status = await _replace(client, headers)
    assert status["review"]["state"] == "needs_review"


async def _say(
    client: AsyncClient,
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
    rounds: list[list[Any]],
) -> list[tuple[str, dict[str, Any]]]:
    _install_stream(monkeypatch, rounds)
    response = await client.post(
        f"/api/v1/consultation/sessions/{session_id}/messages",
        json={"content": "네"},
        headers=headers,
    )
    return _parse_sse(response.text)


def _result(events: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    return next(p for e, p in events if e == "action")["result"]


def _record_state(events: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    return next(p for e, p in events if e == "signal")["record_review"]


async def test_student_resolves_the_record_through_the_chat_and_the_button_imports_it(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _stopped_upload(client, auth_headers, monkeypatch)

    opened = await client.post("/api/v1/consultation/record-review", headers=auth_headers)
    assert opened.status_code == 200, opened.text
    session = opened.json()
    assert session["kind"] == "record_review"
    assert session["stage"] == "record_review"
    review = session["record_review"]
    assert [a["kind"] for a in review["anomalies"]] == ["freshman_year_mismatch"]
    [conflict] = review["conflicts"]
    assert len(review["outstanding"]) == 2
    # 같은 업로드면 같은 세션을 이어 간다.
    again = await client.post("/api/v1/consultation/record-review", headers=auth_headers)
    assert again.json()["id"] == session["id"]

    sid = session["id"]
    early = await _say(
        client, auth_headers, monkeypatch, sid,
        [[_tool_call_chunk("signal_ready_to_conclude", {})], [_chunk("아직 정할 게 있어요.")]],
    )
    assert "error" in _result(early)
    refused = await client.post(
        f"/api/v1/consultation/sessions/{sid}/conclude", headers=auth_headers
    )
    assert refused.status_code == 409

    scoped = await _say(
        client, auth_headers, monkeypatch, sid,
        [
            [_tool_call_chunk("set_record_scope", {"mode": "all", "reason": "생기부가 맞아요"})],
            [_chunk("알겠어요.")],
        ],
    )
    assert _result(scoped)["stored"] is True
    await _say(
        client, auth_headers, monkeypatch, sid,
        [
            [_tool_call_chunk(
                "resolve_record_conflict", {"conflict_id": conflict["id"], "choice": "use_record"}
            )],
            [_chunk("생기부로 바꿀게요.")],
        ],
    )
    ready = await _say(
        client, auth_headers, monkeypatch, sid,
        [[_tool_call_chunk("signal_ready_to_conclude", {})]],
    )
    assert _result(ready) == {"ready": True}
    assert _record_state(ready)["outstanding"] == []

    concluded = await client.post(
        f"/api/v1/consultation/sessions/{sid}/conclude", headers=auth_headers
    )
    assert concluded.status_code == 200, concluded.text
    assert concluded.json()["record_review"]["result_state"] == "resolved"

    async with TestSessionLocal() as db:
        rows = (await db.scalars(select(AcademicPerformance))).all()
    # 학생이 적은 A는 지워지고 생기부의 B가, 그리고 충돌 없던 공통수학1이 들어갔다.
    assert sorted((r.subject, r.achievement_grade) for r in rows) == [
        ("공통수학1", "A"),
        ("공통수학2", "B"),
    ]

    # 생기부 확인 상담을 마쳐도 학기 상담 관문은 열리지 않는다.
    status = (await client.get("/api/v1/consultation/status", headers=auth_headers)).json()
    assert status["satisfied"] is False


async def test_declining_the_record_imports_nothing(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _stopped_upload(client, auth_headers, monkeypatch)
    sid = (await client.post("/api/v1/consultation/record-review", headers=auth_headers)).json()[
        "id"
    ]
    await _say(
        client, auth_headers, monkeypatch, sid,
        [
            [_tool_call_chunk("set_record_scope", {"mode": "none", "reason": "제 것이 아니에요"})],
            [_tool_call_chunk("signal_ready_to_conclude", {})],
        ],
    )

    concluded = await client.post(
        f"/api/v1/consultation/sessions/{sid}/conclude", headers=auth_headers
    )

    assert concluded.json()["record_review"]["result_state"] == "discarded"
    async with TestSessionLocal() as db:
        rows = (await db.scalars(select(AcademicPerformance))).all()
    assert [(r.subject, r.achievement_grade) for r in rows] == [("공통수학2", "A")]
    # 반영하지 않기로 한 업로드로는 다시 확인 상담을 열 수 없다.
    reopened = await client.post("/api/v1/consultation/record-review", headers=auth_headers)
    assert reopened.status_code == 409


async def test_nothing_to_review_is_refused(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _set_profile_grade(client, auth_headers, grade=2, semester=1)
    response = await client.post("/api/v1/consultation/record-review", headers=auth_headers)
    assert response.status_code == 409


async def test_record_review_chat_uses_its_own_prompt_and_keeps_past_semester_talk(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _stopped_upload(client, auth_headers, monkeypatch)
    sid = (await client.post("/api/v1/consultation/record-review", headers=auth_headers)).json()[
        "id"
    ]
    seen: dict[str, Any] = {}

    async def fake_stream_chat(messages, tools=None):
        seen["system"] = messages[0]["content"]
        seen["tools"] = [t["function"]["name"] for t in tools or []]
        yield _chunk("1학년 2학기 공통수학2 성적이 서로 달라요.")

    monkeypatch.setattr(chat_service, "stream_chat", fake_stream_chat)
    response = await client.post(
        f"/api/v1/consultation/sessions/{sid}/messages",
        json={"content": "무슨 문제예요?"},
        headers=auth_headers,
    )

    assert "생기부 확인 담당" in seen["system"]
    assert seen["tools"] == [
        "set_record_scope", "resolve_record_conflict", "signal_ready_to_conclude",
    ]
    tokens = "".join(p["delta"] for e, p in _parse_sse(response.text) if e == "token")
    assert "1학년 2학기 공통수학2 성적이 서로 달라요." in tokens
