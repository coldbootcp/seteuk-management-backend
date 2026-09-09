from httpx import AsyncClient

PROFILE_PAYLOAD = {
    "name": "홍길동",
    "grade": 2,
    "semester": 1,
    "career_goal": {"goal": "AI 연구원", "note": "데이터 기반 의학 연구에도 관심 있음"},
    "target_department": "컴퓨터공학과",
    "interest_keywords": ["머신러닝", "로봇공학"],
    "career_specificity": {
        "level": "specific",
        "known_concepts": ["강화학습"],
        "curious_topics": ["로봇 모션 제어"],
    },
    "preferred_output_types": ["report", "experiment"],
    "activity_channels": ["동아리", "세특보고서"],
    "roadmap_constraints": "방과후 학원 때문에 평일 활동 시간이 부족함",
    "self_assessed_strengths": "수학적 모델링에 강함",
    "self_assessed_weaknesses": "실제 데이터 분석 경험 부족",
}


async def test_set_profile_persists_and_is_readable(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    post_response = await client.post(
        "/api/v1/profile", headers=auth_headers, json=PROFILE_PAYLOAD
    )
    assert post_response.status_code == 200
    body = post_response.json()
    assert body["name"] == "홍길동"
    assert body["grade"] == 2
    assert body["career_goal"]["goal"] == "AI 연구원"
    assert body["interest_keywords"] == ["머신러닝", "로봇공학"]

    get_response = await client.get("/api/v1/profile/me", headers=auth_headers)
    assert get_response.status_code == 200
    assert get_response.json() == body


async def test_get_profile_before_onboarding_returns_empty_fields(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/profile/me", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["name"] is None
    assert body["career_goal"] is None
    assert body["interest_keywords"] == []


async def test_set_profile_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/api/v1/profile", json=PROFILE_PAYLOAD)

    assert response.status_code == 401
