import pytest
from httpx import AsyncClient

import app.services.recommendation_service as recommendation_service
from app.schemas.recommendation import RecommendationDraft

CAPTURED: dict[str, str] = {}


async def _fake_follow_up(system_prompt: str, user_content: str, response_model: type):
    assert response_model is RecommendationDraft
    CAPTURED["user_content"] = user_content
    # 세 선택지는 난이도·접근이 서로 달라야 한다는 것이 명세다. 표현만 다른 같은
    # 주제를 내면 Reviewer가 걸러내므로, fake도 실제처럼 서로 다른 주제를 낸다.
    topics = [
        "실측 데이터로 지수함수 모델 검증",
        "로지스틱 곡선과 비교해 포화 구간 해석",
        "설문으로 이용자 체감 대기시간 조사",
    ]
    return RecommendationDraft(
        options=[
            {
                "topic": topic,
                "connection_reason": "원래 활동의 한계에서 출발했다.",
                "subject_relevance": "수학Ⅰ 지수함수 단원과 연결된다.",
                "career_relevance": "AI 연구원 진로와 맞닿아 있다.",
                "record_potential": "생기부에 이렇게 남을 수 있다.",
                "difficulty": "medium",
                "materials": ["공개 확진자 데이터셋"],
                "expected_output": "검증 보고서",
                "expansion_potential": "3학년에 시뮬레이션으로 확장 가능.",
            }
            for topic in topics
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
    assert plan["title"] == "로지스틱 곡선과 비교해 포화 구간 해석"
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


async def _new_recommendation(client: AsyncClient, headers: dict[str, str]) -> str:
    activity_id = await _create_activity(client, headers)
    created = await client.post(
        "/api/v1/recommendations/follow-up",
        json={"source_activity_id": activity_id},
        headers=headers,
    )
    return created.json()["id"]


async def test_feedback_is_append_only(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """마음이 바뀌어도 이전 기록을 고치지 않고 새 행을 쌓는다 — "저장했다가 나중에
    거절했다"는 것 자체가 다음 추천의 신호이기 때문이다."""
    recommendation_id = await _new_recommendation(client, auth_headers)

    first = await client.post(
        f"/api/v1/recommendations/{recommendation_id}/feedback",
        json={"option_index": 0, "action": "saved"},
        headers=auth_headers,
    )
    assert first.status_code == 201

    await client.post(
        f"/api/v1/recommendations/{recommendation_id}/feedback",
        json={"option_index": 0, "action": "rejected", "reason": "생각보다 범위가 넓다"},
        headers=auth_headers,
    )

    history = (
        await client.get("/api/v1/recommendations/feedback/history", headers=auth_headers)
    ).json()
    # 같은 선택지에 대한 두 기록이 모두 남는다(최신이 먼저).
    assert [f["action"] for f in history] == ["rejected", "saved"]
    assert history[0]["reason"] == "생각보다 범위가 넓다"


async def test_feedback_rejects_an_option_index_that_does_not_exist(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    recommendation_id = await _new_recommendation(client, auth_headers)

    response = await client.post(
        f"/api/v1/recommendations/{recommendation_id}/feedback",
        json={"option_index": 9, "action": "saved"},
        headers=auth_headers,
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "RECOMMENDATION_NOT_FOUND"


async def test_feedback_is_scoped_to_its_owner(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    recommendation_id = await _new_recommendation(client, auth_headers)
    signup = await client.post(
        "/api/v1/auth/signup",
        json={"email": "other-feedback@example.com", "password": "s3cure-passw0rd"},
    )
    other = {"Authorization": f"Bearer {signup.json()['access_token']}"}

    response = await client.post(
        f"/api/v1/recommendations/{recommendation_id}/feedback",
        json={"option_index": 0, "action": "saved"},
        headers=other,
    )
    assert response.status_code == 404


async def test_review_drops_an_option_that_repeats_an_existing_plan(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """생성된 추천은 후보일 뿐이다(P-3). 이미 세운 계획을 다시 제안하면 학생에게는
    새 선택지가 아니므로 검수 단계가 걸러낸다."""
    await client.post(
        "/api/v1/plans",
        json={"item_type": "activity", "title": "실측 데이터로 지수함수 모델 검증"},
        headers=auth_headers,
    )
    activity_id = await _create_activity(client, auth_headers)

    created = await client.post(
        "/api/v1/recommendations/follow-up",
        json={"source_activity_id": activity_id},
        headers=auth_headers,
    )
    topics = [o["topic"] for o in created.json()["options"]]
    assert "실측 데이터로 지수함수 모델 검증" not in topics
    assert len(topics) == 2


async def test_every_option_rejected_still_shows_something(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """검수가 전부 떨어뜨리면 화면이 비어 버린다. 빈 화면보다 흠 있는 선택지가 낫다."""

    async def _all_unsafe(system_prompt: str, user_content: str, response_model: type):
        return RecommendationDraft(
            options=[
                {
                    "topic": "무조건 합격하는 탐구",
                    "connection_reason": "이 활동이면 서울대에 합격할 수 있습니다.",
                    "subject_relevance": "x",
                    "career_relevance": "x",
                    "record_potential": "x",
                    "difficulty": "medium",
                    "materials": [],
                    "expected_output": "x",
                    "expansion_potential": "x",
                }
            ]
        )

    monkeypatch.setattr(recommendation_service, "call_structured", _all_unsafe)
    activity_id = await _create_activity(client, auth_headers)

    created = await client.post(
        "/api/v1/recommendations/follow-up",
        json={"source_activity_id": activity_id},
        headers=auth_headers,
    )
    assert created.status_code == 201
    assert len(created.json()["options"]) == 1
