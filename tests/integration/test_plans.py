import json

import pytest
from httpx import AsyncClient

import app.services.plan_service as plan_service
from app.schemas.plan import RoadmapDraft


async def _fake_roadmap(system_prompt: str, user_content: str, response_model: type):
    assert response_model is RoadmapDraft
    return RoadmapDraft(
        semesters=[
            {
                "grade": 2,
                "semester": 2,
                "theme": "모델링 심화",
                "rationale": "1학기 지수함수 모델을 실제 데이터로 검증하는 단계.",
                "items": [
                    {
                        "item_type": "activity",
                        "title": "실제 확진자 데이터로 모델 검증",
                        "description": "공개 데이터로 예측값과 실측값을 비교한다.",
                        "subject": "수학Ⅰ",
                        "keywords": ["데이터 분석"],
                        "source_activity_index": None,
                    }
                ],
            },
            {
                # 대상 학기 밖의 학기는 서비스가 버려야 한다.
                "grade": 1,
                "semester": 1,
                "theme": "이미 지난 학기",
                "rationale": "무시되어야 한다.",
                "items": [],
            },
        ]
    )


async def _fake_roadmap_linking_first_past_activity(
    system_prompt: str, user_content: str, response_model: type
):
    """past_activities의 첫 번째 활동을 index=1로 잇는 계획을 낸다 — UUID가
    아니라 index로 참조하는 새 계약을 실제로 검증하기 위한 fake."""
    assert response_model is RoadmapDraft
    payload = json.loads(user_content)
    assert payload["past_activities"], "이 fake는 과거 활동이 있는 시나리오에서만 써야 함"
    return RoadmapDraft(
        semesters=[
            {
                "grade": 2,
                "semester": 2,
                "theme": "심화 단계",
                "rationale": "이전 활동을 심화한다.",
                "items": [
                    {
                        "item_type": "activity",
                        "title": "이전 활동을 잇는 후속 탐구",
                        "description": "직전 활동의 한계를 보완한다.",
                        "subject": None,
                        "keywords": [],
                        "source_activity_index": 1,
                    },
                    {
                        # 존재하지 않는 index — 서비스가 조용히 버려야 한다.
                        "item_type": "activity",
                        "title": "지어낸 index를 가리키는 계획",
                        "description": "이 계획의 source는 무시되어야 한다.",
                        "subject": None,
                        "keywords": [],
                        "source_activity_index": 999,
                    },
                ],
            }
        ]
    )


@pytest.fixture(autouse=True)
def _patch_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plan_service, "call_structured", _fake_roadmap)


async def _onboard(client: AsyncClient, headers: dict[str, str]) -> None:
    await client.post(
        "/api/v1/profile",
        json={
            "name": "홍길동",
            "grade": 2,
            "semester": 1,
            "career_goal": {"goal": "AI 연구원"},
            "target_department": "컴퓨터공학과",
            "interest_keywords": ["머신러닝"],
            "career_specificity": {"level": "specific"},
            "preferred_output_types": ["report"],
            "activity_channels": ["동아리"],
            "self_assessed_strengths": "수학적 모델링에 강함",
            "self_assessed_weaknesses": "데이터 분석 경험 부족",
        },
        headers=headers,
    )
    assert (await client.get("/api/v1/profile/me", headers=headers)).json()["grade"] == 2


async def test_plan_crud_and_filters(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    created = await client.post(
        "/api/v1/plans",
        json={
            "item_type": "reading",
            "title": "이기적 유전자 읽기",
            "target_grade": 2,
            "target_semester": 2,
        },
        headers=auth_headers,
    )
    assert created.status_code == 201
    plan = created.json()
    assert plan["status"] == "planned"
    assert plan["origin"] == "user"

    listed = await client.get(
        "/api/v1/plans", params={"status": "planned"}, headers=auth_headers
    )
    assert listed.json()["total"] == 1

    patched = await client.patch(
        f"/api/v1/plans/{plan['id']}", json={"status": "in_progress"}, headers=auth_headers
    )
    assert patched.json()["status"] == "in_progress"

    assert (
        await client.delete(f"/api/v1/plans/{plan['id']}", headers=auth_headers)
    ).status_code == 204


async def test_completing_activity_plan_promotes_it_and_keeps_lineage(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _onboard(client, auth_headers)
    source = await client.post(
        "/api/v1/activities",
        json={
            "grade": 2,
            "semester": 1,
            "activity_category": "과목세부특기사항",
            "activity_name": "감염병 확산 모델",
            "activity_type": "report",
            "description": "지수함수 모델링",
        },
        headers=auth_headers,
    )
    source_id = source.json()["id"]

    plan = await client.post(
        "/api/v1/plans",
        json={
            "item_type": "activity",
            "title": "SIR 모델로 확장",
            "description": "감염병 모델을 SIR로 확장한다.",
            "target_grade": 2,
            "target_semester": 2,
            "source_activity_id": source_id,
        },
        headers=auth_headers,
    )
    plan_id = plan.json()["id"]

    completed = await client.post(
        f"/api/v1/plans/{plan_id}/complete",
        json={"activity_type": "report"},
        headers=auth_headers,
    )
    assert completed.status_code == 200
    body = completed.json()
    assert body["plan_item"]["status"] == "done"
    new_activity_id = body["created_activity_id"]
    assert new_activity_id is not None

    # 승격된 활동은 계획이 매달려 있던 과거 활동의 자식이 된다.
    activity = await client.get(f"/api/v1/activities/{new_activity_id}", headers=auth_headers)
    assert activity.json()["parent_activity_id"] == source_id
    assert activity.json()["grade"] == 2
    assert activity.json()["semester"] == 2

    lineage = await client.get(f"/api/v1/activities/{source_id}/lineage", headers=auth_headers)
    kinds = [(n["kind"], n["title"]) for n in lineage.json()["nodes"]]
    assert kinds == [("activity", "감염병 확산 모델"), ("activity", "SIR 모델로 확장")]

    # 두 번 완료 처리하면 기록이 중복 생성되므로 막는다.
    again = await client.post(
        f"/api/v1/plans/{plan_id}/complete", json={}, headers=auth_headers
    )
    assert again.status_code == 409
    assert again.json()["error_code"] == "INVALID_PLAN_TRANSITION"


async def test_completing_reading_plan_creates_reading_row(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _onboard(client, auth_headers)
    plan = await client.post(
        "/api/v1/plans",
        json={"item_type": "reading", "title": "총, 균, 쇠", "target_grade": 3},
        headers=auth_headers,
    )
    completed = await client.post(
        f"/api/v1/plans/{plan.json()['id']}/complete",
        json={"author": "재레드 다이아몬드"},
        headers=auth_headers,
    )
    assert completed.json()["created_reading_id"] is not None

    readings = await client.get("/api/v1/reading-activities", headers=auth_headers)
    item = readings.json()["items"][0]
    assert item["title"] == "총, 균, 쇠"
    assert item["author"] == "재레드 다이아몬드"
    assert item["grade"] == 3


async def test_roadmap_creates_plan_items_for_remaining_semesters(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _onboard(client, auth_headers)
    response = await client.post("/api/v1/plans/roadmap", json={}, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()

    # 2학년 1학기가 현재이므로 대상은 2-2부터 — 1-1 제안은 걸러진다.
    assert [(s["grade"], s["semester"]) for s in body["semesters"]] == [(2, 2)]
    assert len(body["created_plan_items"]) == 1
    assert body["created_plan_items"][0]["origin"] == "ai_roadmap"

    listed = await client.get("/api/v1/plans", headers=auth_headers)
    assert listed.json()["total"] == 1


async def test_roadmap_regeneration_keeps_user_plans(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _onboard(client, auth_headers)
    await client.post(
        "/api/v1/plans",
        json={"item_type": "reading", "title": "내가 직접 세운 계획", "target_grade": 2,
              "target_semester": 2},
        headers=auth_headers,
    )
    await client.post("/api/v1/plans/roadmap", json={}, headers=auth_headers)
    await client.post("/api/v1/plans/roadmap", json={}, headers=auth_headers)

    listed = await client.get("/api/v1/plans", headers=auth_headers)
    titles = sorted(item["title"] for item in listed.json()["items"])
    # 재생성이 사용자 계획을 삼키지 않고, AI 계획도 중복되지 않아야 한다.
    assert titles == ["내가 직접 세운 계획", "실제 확진자 데이터로 모델 검증"]


async def test_roadmap_resolves_source_activity_index_to_real_activity(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM이 activity_id를 직접 베끼지 않고 index로만 참조하는 새 계약을 검증한다.
    존재하는 index는 실제 활동으로 이어지고, 지어낸 index는 조용히 버려져야 한다."""
    await _onboard(client, auth_headers)
    activity = await client.post(
        "/api/v1/activities",
        json={
            "grade": 2,
            "semester": 1,
            "activity_category": "과목세부특기사항",
            "activity_name": "로지스틱 함수로 확산 곡선 보정",
            "activity_type": "report",
            "description": "지수함수 모델의 한계를 로지스틱 함수로 보완함.",
        },
        headers=auth_headers,
    )
    activity_id = activity.json()["id"]

    monkeypatch.setattr(
        plan_service, "call_structured", _fake_roadmap_linking_first_past_activity
    )
    response = await client.post("/api/v1/plans/roadmap", json={}, headers=auth_headers)
    assert response.status_code == 200
    created = response.json()["created_plan_items"]
    assert len(created) == 2

    linked = next(p for p in created if p["title"] == "이전 활동을 잇는 후속 탐구")
    assert linked["source_activity_id"] == activity_id

    bogus = next(p for p in created if p["title"] == "지어낸 index를 가리키는 계획")
    assert bogus["source_activity_id"] is None
