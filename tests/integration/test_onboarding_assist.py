import pytest
from httpx import AsyncClient

import app.services.profile_service as profile_service
import app.services.roadmap_service as roadmap_service
from app.schemas.profile import SuggestResponse
from app.schemas.roadmap import NodeSummaryDraft

CAPTURED: dict[str, str] = {}


async def _fake_call(system_prompt: str, user_content: str, response_model: type):
    CAPTURED["user_content"] = user_content
    if response_model is SuggestResponse:
        return SuggestResponse(
            majors=["산업공학과", "컴퓨터공학과"], keywords=["데이터 기반 문제 해결"]
        )
    if response_model is NodeSummaryDraft:
        return NodeSummaryDraft(summary="이 학기는 데이터 분석 갈래로 채워졌습니다.")
    raise AssertionError(f"unexpected response_model: {response_model}")


@pytest.fixture(autouse=True)
def _patch_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profile_service, "call_structured", _fake_call)
    monkeypatch.setattr(roadmap_service, "call_structured", _fake_call)


async def test_suggest_offers_candidates_without_saving_anything(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """제안은 제안일 뿐이다 — 학생이 고른 값만 POST /profile로 확정된다."""
    response = await client.post(
        "/api/v1/profile/suggest", json={"career_goal": "데이터 기반 연구직"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert "산업공학과" in response.json()["majors"]

    # 프로필은 여전히 비어 있다.
    profile = await client.get("/api/v1/profile/me", headers=auth_headers)
    assert profile.json()["target_department"] is None


async def test_node_summary_uses_only_that_semesters_activities(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """활성 마디라고 해서 관련 없는 활동까지 끌어오면 근거 없는 요약이 된다."""
    await client.post(
        "/api/v1/profile",
        json={
            "name": "홍길동",
            "grade": 2,
            "semester": 1,
            "career_goal": {"goal": "연구원"},
            "target_department": "산업공학과",
            "interest_keywords": [],
            "career_specificity": {"level": "broad"},
            "preferred_output_types": [],
            "activity_channels": [],
            "self_assessed_strengths": "x",
            "self_assessed_weaknesses": "y",
        },
        headers=auth_headers,
    )
    for grade, semester, name in ((2, 1, "이번 학기 활동"), (1, 1, "지난 학기 활동")):
        await client.post(
            "/api/v1/activities",
            json={
                "grade": grade,
                "semester": semester,
                "activity_category": "과목세부특기사항",
                "activity_name": name,
                "activity_type": "report",
                "description": "설명",
            },
            headers=auth_headers,
        )

    roadmap = (await client.post("/api/v1/roadmaps", json={}, headers=auth_headers)).json()
    node = next(n for n in roadmap["nodes"] if (n["grade"], n["semester"]) == (2, 1))

    response = await client.post(
        f"/api/v1/roadmaps/nodes/{node['id']}/summarize", headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["summary"]

    assert "이번 학기 활동" in CAPTURED["user_content"]
    assert "지난 학기 활동" not in CAPTURED["user_content"]
