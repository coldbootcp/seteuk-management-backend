import pytest
from httpx import AsyncClient

import app.services.recommendation_service as recommendation_service
from app.schemas.recommendation import RecommendationDraft

CAPTURED: dict[str, str] = {}


async def _fake_follow_up(system_prompt: str, user_content: str, response_model: type):
    assert response_model is RecommendationDraft
    CAPTURED["user_content"] = user_content
    return RecommendationDraft(
        options=[
            {
                "topic": f"후속 주제 {index}",
                "connection_reason": "원래 활동의 한계에서 출발했다.",
                "subject_relevance": "수학Ⅰ 지수함수 단원과 연결된다.",
                "career_relevance": "AI 연구원 진로와 맞닿아 있다.",
                "record_potential": "생기부에 이렇게 남을 수 있다.",
                "difficulty": "medium",
                "materials": ["공개 확진자 데이터셋"],
                "expected_output": "검증 보고서",
                "expansion_potential": "3학년에 시뮬레이션으로 확장 가능.",
            }
            for index in range(3)
        ]
    )


@pytest.fixture(autouse=True)
def _patch_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recommendation_service, "call_structured", _fake_follow_up)


async def _create_activity(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/activities",
        json={
            "grade": 2,
            "semester": 1,
            "activity_category": "과목세부특기사항",
            "subject": "수학Ⅰ",
            "activity_name": "감염병 확산과 지수함수 모델",
            "activity_type": "report",
            "description": "지수함수로 확산 곡선을 모델링했다.",
            "keywords": ["수학적 모델링"],
        },
        headers=headers,
    )
    return response.json()["id"]


async def test_follow_up_uses_source_activity_and_lineage(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    activity_id = await _create_activity(client, auth_headers)
    response = await client.post(
        "/api/v1/recommendations/follow-up",
        json={"source_activity_id": activity_id, "desired_activity_type": "experiment"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert len(body["options"]) == 3
    assert body["desired_activity_type"] == "experiment"

    # 범용 추천이 아니라 원본 활동과 사슬을 근거로 삼는지 — 프롬프트 입력을 검사한다.
    assert "감염병 확산과 지수함수 모델" in CAPTURED["user_content"]
    assert "lineage" in CAPTURED["user_content"]

    fetched = await client.get(f"/api/v1/recommendations/{body['id']}", headers=auth_headers)
    assert fetched.json()["id"] == body["id"]


async def test_follow_up_rejects_unknown_activity(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/recommendations/follow-up",
        json={"source_activity_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers,
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "ACTIVITY_NOT_FOUND"


async def test_adopting_option_creates_plan_linked_to_source_activity(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    activity_id = await _create_activity(client, auth_headers)
    recommendation = await client.post(
        "/api/v1/recommendations/follow-up",
        json={"source_activity_id": activity_id},
        headers=auth_headers,
    )
    recommendation_id = recommendation.json()["id"]

    adopted = await client.post(
        f"/api/v1/recommendations/{recommendation_id}/adopt",
        json={"option_index": 1, "target_grade": 2, "target_semester": 2},
        headers=auth_headers,
    )
    assert adopted.status_code == 201
    plan = adopted.json()
    assert plan["title"] == "후속 주제 1"
    assert plan["origin"] == "recommendation"
    assert plan["source_activity_id"] == activity_id
    assert plan["source_recommendation_id"] == recommendation_id

    # 담긴 계획은 원본 활동의 계보에 미래 노드로 붙는다.
    lineage = await client.get(f"/api/v1/activities/{activity_id}/lineage", headers=auth_headers)
    nodes = lineage.json()["nodes"]
    assert [n["kind"] for n in nodes] == ["activity", "plan"]
    assert nodes[1]["status"] == "planned"


async def test_adopting_out_of_range_option_is_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    activity_id = await _create_activity(client, auth_headers)
    recommendation = await client.post(
        "/api/v1/recommendations/follow-up",
        json={"source_activity_id": activity_id},
        headers=auth_headers,
    )
    response = await client.post(
        f"/api/v1/recommendations/{recommendation.json()['id']}/adopt",
        json={"option_index": 9},
        headers=auth_headers,
    )
    assert response.status_code == 404
