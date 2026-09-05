import pytest
from httpx import AsyncClient


@pytest.fixture
async def other_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/signup",
        json={"email": "other-student@example.com", "password": "s3cure-passw0rd"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


ACTIVITY_PAYLOAD = {
    "grade": 2,
    "semester": 1,
    "activity_category": "과목세부특기사항",
    "subject": "수학Ⅰ",
    "activity_name": "감염병 확산과 지수함수 모델",
    "activity_type": "report",
    "description": "지수함수로 확산 곡선을 모델링했다.",
    "keywords": ["수학적 모델링"],
}


async def test_activity_crud_roundtrip(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    created = await client.post("/api/v1/activities", json=ACTIVITY_PAYLOAD, headers=auth_headers)
    assert created.status_code == 201
    body = created.json()
    activity_id = body["id"]
    # 직접 입력한 행은 생기부발이 아니므로 재업로드에 지워지지 않아야 한다.
    assert body["source_upload_id"] is None

    listed = await client.get(
        "/api/v1/activities", params={"activity_type": "report"}, headers=auth_headers
    )
    assert listed.json()["total"] == 1

    filtered_out = await client.get(
        "/api/v1/activities", params={"grade": 3}, headers=auth_headers
    )
    assert filtered_out.json()["total"] == 0

    patched = await client.patch(
        f"/api/v1/activities/{activity_id}",
        json={"activity_name": "감염병 확산 모델 심화"},
        headers=auth_headers,
    )
    assert patched.json()["activity_name"] == "감염병 확산 모델 심화"
    assert patched.json()["description"] == ACTIVITY_PAYLOAD["description"]

    deleted = await client.delete(f"/api/v1/activities/{activity_id}", headers=auth_headers)
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/activities", headers=auth_headers)).json()["total"] == 0


async def test_records_are_scoped_to_owner(
    client: AsyncClient, auth_headers: dict[str, str], other_headers: dict[str, str]
) -> None:
    created = await client.post("/api/v1/activities", json=ACTIVITY_PAYLOAD, headers=auth_headers)
    activity_id = created.json()["id"]

    assert (await client.get("/api/v1/activities", headers=other_headers)).json()["total"] == 0
    stolen = await client.get(f"/api/v1/activities/{activity_id}", headers=other_headers)
    assert stolen.status_code == 404
    assert stolen.json()["error_code"] == "RECORD_NOT_FOUND"


async def test_all_record_tabs_accept_manual_entry(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    payloads = {
        "/api/v1/attendance": {"grade": 2, "total_days": 190, "absence": 1},
        "/api/v1/academic-performance": {
            "grade": 2,
            "semester": 1,
            "category": "수학",
            "subject": "수학Ⅰ",
            "achievement_grade": "A",
        },
        "/api/v1/reading-activities": {"grade": 2, "title": "이기적 유전자"},
        "/api/v1/awards": {"name": "수학 경시대회", "rank": "금상"},
        "/api/v1/volunteer-records": {"grade": 2, "place": "지역아동센터", "hours": 8},
    }
    for path, payload in payloads.items():
        created = await client.post(path, json=payload, headers=auth_headers)
        assert created.status_code == 201, (path, created.text)
        listed = await client.get(path, headers=auth_headers)
        assert listed.json()["total"] == 1, path


async def test_activity_lineage_returns_whole_chain(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    root = await client.post("/api/v1/activities", json=ACTIVITY_PAYLOAD, headers=auth_headers)
    root_id = root.json()["id"]

    child_payload = ACTIVITY_PAYLOAD | {
        "grade": 3,
        "activity_name": "SIR 모델로 확장한 확산 시뮬레이션",
        "parent_activity_id": root_id,
    }
    child = await client.post("/api/v1/activities", json=child_payload, headers=auth_headers)
    child_id = child.json()["id"]

    # 계보는 자식 쪽에서 물어봐도 뿌리까지 거슬러 올라간 전체 사슬을 준다.
    lineage = await client.get(f"/api/v1/activities/{child_id}/lineage", headers=auth_headers)
    nodes = lineage.json()["nodes"]
    assert [n["id"] for n in nodes] == [root_id, child_id]
    assert nodes[1]["parent_id"] == root_id
