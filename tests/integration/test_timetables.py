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


async def test_timetable_slots_keep_catalog_codes_and_reject_unknown_ones(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    def payload(slot: dict) -> dict:
        return {
            "timetables": [
                {"name": "기본", "grade": 2, "semester": 1, "is_default": True, "slots": [slot]}
            ]
        }

    picked = {**_slot("slot-a", "대수"), "subject_code": "2022:대수"}
    response = await client.put("/api/v1/timetables", headers=auth_headers, json=payload(picked))
    assert response.status_code == 200
    assert response.json()["timetables"][0]["slots"][0]["subject_code"] == "2022:대수"

    # 기타로 직접 적은 과목(과 예전에 저장된 칸)은 코드 없이 저장된다.
    custom = _slot("slot-b", "학교 자율 탐구")
    response = await client.put("/api/v1/timetables", headers=auth_headers, json=payload(custom))
    assert response.status_code == 200
    assert response.json()["timetables"][0]["slots"][0]["subject_code"] is None

    made_up = {**_slot("slot-c", "수학"), "subject_code": "2022:없는과목"}
    response = await client.put("/api/v1/timetables", headers=auth_headers, json=payload(made_up))
    assert response.status_code == 422
