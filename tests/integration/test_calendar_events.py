import pytest
from httpx import AsyncClient

EXAM_PAYLOAD = {
    "event_type": "시험",
    "title": "1학기 기말고사",
    "start_date": "2026-07-06",
    "end_date": "2026-07-09",
}

ASSESSMENT_PAYLOAD = {
    "event_type": "수행평가",
    "title": "확률과 통계 수행평가",
    "subject": "확률과 통계",
    "start_date": "2026-06-01",
    "end_date": "2026-06-01",
    "memo": "포트폴리오 제출형",
}


async def test_calendar_event_crud_roundtrip(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/v1/calendar-events", json=EXAM_PAYLOAD, headers=auth_headers
    )
    assert created.status_code == 201
    event_id = created.json()["id"]
    assert created.json()["subject"] is None

    listed = await client.get(
        "/api/v1/calendar-events", params={"event_type": "시험"}, headers=auth_headers
    )
    assert listed.json()["total"] == 1

    patched = await client.patch(
        f"/api/v1/calendar-events/{event_id}",
        json={"title": "1학기 기말고사 (변경)"},
        headers=auth_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "1학기 기말고사 (변경)"
    # 손대지 않은 필드는 그대로 남는다.
    assert patched.json()["start_date"] == EXAM_PAYLOAD["start_date"]

    deleted = await client.delete(f"/api/v1/calendar-events/{event_id}", headers=auth_headers)
    assert deleted.status_code == 204
    assert (
        await client.get("/api/v1/calendar-events", headers=auth_headers)
    ).json()["total"] == 0


async def test_calendar_event_with_subject_and_memo(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/v1/calendar-events", json=ASSESSMENT_PAYLOAD, headers=auth_headers
    )
    assert created.status_code == 201
    body = created.json()
    assert body["subject"] == "확률과 통계"
    assert body["memo"] == "포트폴리오 제출형"


async def test_calendar_event_rejects_end_before_start(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/calendar-events",
        json={**EXAM_PAYLOAD, "start_date": "2026-07-09", "end_date": "2026-07-06"},
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.fixture
async def other_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/signup",
        json={"email": "other-calendar-user@example.com", "password": "s3cure-passw0rd"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_calendar_events_are_scoped_to_owner(
    client: AsyncClient, auth_headers: dict[str, str], other_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/v1/calendar-events", json=EXAM_PAYLOAD, headers=auth_headers
    )
    event_id = created.json()["id"]

    assert (
        await client.get("/api/v1/calendar-events", headers=other_headers)
    ).json()["total"] == 0
    stolen = await client.get(f"/api/v1/calendar-events/{event_id}", headers=other_headers)
    assert stolen.status_code == 404
