from httpx import AsyncClient


def _slot(slot_id: str, course_name: str = "공통수학1") -> dict:
    return {
        "id": slot_id,
        "course_name": course_name,
        "teacher": "김교사",
        "room": "201",
        "day": 0,
        "start_period": 1,
        "period_span": 1,
        "category": "공통",
        "group": "수학",
        "color_index": 0,
        "units": 4,
        "is_career_related": False,
    }


async def test_timetable_sync_persists_slots_for_the_same_user(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.put(
        "/api/v1/timetables",
        headers=auth_headers,
        json={
            "timetables": [
                {
                    "name": "1학년 1학기 기본 시간표",
                    "grade": 1,
                    "semester": 1,
                    "is_default": True,
                    "slots": [_slot("slot-local-1")],
                }
            ]
        },
    )
    assert response.status_code == 200
    saved = response.json()["timetables"]
    assert len(saved) == 1
    assert saved[0]["slots"][0]["course_name"] == "공통수학1"

    listed = await client.get("/api/v1/timetables", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()["timetables"] == saved


async def test_timetable_sync_rejects_another_users_id(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    first = await client.put(
        "/api/v1/timetables",
        headers=auth_headers,
        json={
            "timetables": [
                {
                    "name": "내 시간표",
                    "grade": 1,
                    "semester": 1,
                    "is_default": True,
                    "slots": [],
                }
            ]
        },
    )
    timetable_id = first.json()["timetables"][0]["id"]

    other = await client.post(
        "/api/v1/auth/signup",
        json={"email": "other-timetable@example.com", "password": "s3cure-passw0rd"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    response = await client.put(
        "/api/v1/timetables",
        headers=other_headers,
        json={
            "timetables": [
                {
                    "id": timetable_id,
                    "name": "남의 시간표",
                    "grade": 1,
                    "semester": 1,
                    "is_default": True,
                    "slots": [],
                }
            ]
        },
    )
    assert response.status_code == 404
