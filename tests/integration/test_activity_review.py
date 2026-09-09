import pytest
from httpx import AsyncClient

import app.services.activity_review_service as activity_review_service
from app.schemas.roadmap import ActivityReviewDraft

CAPTURED: dict[str, str] = {}


async def _fake_review(system_prompt: str, user_content: str, response_model: type):
    assert response_model is ActivityReviewDraft
    CAPTURED["user_content"] = user_content
    return ActivityReviewDraft(
        alignment="partial",
        summary="원리를 다뤘지만 정량 분석까지는 가지 않았습니다.",
        evidence=["오차 범위를 반복 측정으로 계산함"],
        gaps=["측정값을 모형과 비교하지 않음"],
        next_steps=["같은 데이터를 회귀모형에 넣어 예측값과 비교해보기"],
    )


@pytest.fixture(autouse=True)
def _patch_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(activity_review_service, "call_structured", _fake_review)


async def _new_activity(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/activities",
        json={
            "grade": 2,
            "semester": 1,
            "activity_category": "과목세부특기사항",
            "subject": "물리학",
            "activity_name": "등가속도 운동 오차 분석",
            "activity_type": "experiment",
            "description": "반복 측정으로 표준편차를 계산했다.",
        },
        headers=headers,
    )
    return response.json()["id"]


async def test_review_gives_evidence_gaps_and_next_steps(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """정합 판정은 로드맵 진척을 옮기고, 검토는 학생에게 다음 한 걸음을 준다.
    둘은 다른 질문에 답한다."""
    activity_id = await _new_activity(client, auth_headers)

    created = await client.post(f"/api/v1/activities/{activity_id}/review", headers=auth_headers)
    assert created.status_code == 201
    body = created.json()
    assert body["alignment"] == "partial"
    assert body["evidence"] and body["gaps"] and body["next_steps"]
    assert body["activity_id"] == activity_id

    # 활동 내용이 실제로 프롬프트에 실린다.
    assert "등가속도" in CAPTURED["user_content"]


async def test_reviews_are_kept_but_only_the_latest_is_listed(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """활동을 고친 뒤 다시 검토하면 이전 판단도 남아 있어야 무엇이 달라졌는지 볼 수
    있다. 다만 화면이 보여주는 것은 지금의 판단이다."""
    activity_id = await _new_activity(client, auth_headers)

    first = await client.post(f"/api/v1/activities/{activity_id}/review", headers=auth_headers)
    second = await client.post(f"/api/v1/activities/{activity_id}/review", headers=auth_headers)
    assert first.json()["id"] != second.json()["id"]

    listed = await client.get("/api/v1/activities/reviews/history", headers=auth_headers)
    assert [r["id"] for r in listed.json()] == [second.json()["id"]]


async def test_review_uses_the_roadmap_node_for_that_semester_when_there_is_one(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await client.post(
        "/api/v1/profile",
        json={
            "name": "홍길동",
            "grade": 2,
            "semester": 1,
            "career_goal": {"goal": "연구원"},
            "target_department": "물리학과",
            "interest_keywords": ["오차"],
            "career_specificity": {"level": "broad"},
            "preferred_output_types": [],
            "activity_channels": [],
            "self_assessed_strengths": "x",
            "self_assessed_weaknesses": "y",
        },
        headers=auth_headers,
    )
    await client.post("/api/v1/roadmaps", json={}, headers=auth_headers)
    activity_id = await _new_activity(client, auth_headers)

    created = await client.post(f"/api/v1/activities/{activity_id}/review", headers=auth_headers)
    assert created.json()["roadmap_node_id"] is not None
    # 그 학기 마디의 목표가 프롬프트에 함께 들어간다.
    assert "roadmap_node" in CAPTURED["user_content"]
    assert "narrative_stage" in CAPTURED["user_content"]


async def test_review_is_scoped_to_its_owner(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    activity_id = await _new_activity(client, auth_headers)
    signup = await client.post(
        "/api/v1/auth/signup",
        json={"email": "other-review@example.com", "password": "s3cure-passw0rd"},
    )
    other = {"Authorization": f"Bearer {signup.json()['access_token']}"}

    response = await client.post(f"/api/v1/activities/{activity_id}/review", headers=other)
    assert response.status_code == 404
