import pytest

from app.models.admission_catalog import AdmissionProgram, University
from tests.conftest import TestSessionLocal


@pytest.mark.asyncio
async def test_student_can_save_only_own_activity_as_writing_evidence(client, auth_headers) -> None:
    university = University(official_code="test-u", name="테스트대학교", source_url="https://example.edu")
    async with TestSessionLocal() as db:
        db.add(university)
        await db.flush()
        program = AdmissionProgram(
            university_id=university.id,
            admission_year=2027,
            name="테스트학과",
            source_url="https://example.edu/2027",
        )
        db.add(program)
        await db.commit()

    signup = await client.post(
        "/api/v1/auth/signup",
        json={"email": "preparation-owner@example.com", "password": "s3cure-passw0rd"},
    )
    owner_headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    activity = await client.post(
        "/api/v1/activities",
        headers=owner_headers,
        json={
            "grade": 2,
            "semester": 1,
            "activity_category": "수행평가",
            "activity_name": "반도체 탐구",
            "activity_type": "report",
            "description": "공정 자료를 비교해 반도체 소자 특성을 탐구했다.",
            "keywords": ["반도체"],
        },
    )
    created = await client.post(
        "/api/v1/application-preparations",
        headers=owner_headers,
        json={
            "university_id": str(university.id),
            "program_id": str(program.id),
            "admission_year": 2027,
        },
    )
    assert created.status_code == 201
    preparation_id = created.json()["id"]
    saved = await client.put(
        f"/api/v1/application-preparations/{preparation_id}",
        headers=owner_headers,
        json={
            "central_question": "소자 특성을 어떤 관점으로 탐구해 왔는가",
            "narrative_outline": [{"label": "탐구의 확장", "note": "자료 비교"}],
            "evidence": [
                {
                    "activity_id": activity.json()["id"],
                    "narrative_role": "exploration",
                    "order_index": 1,
                }
            ],
        },
    )
    assert saved.status_code == 200
    assert saved.json()["evidence"][0]["readiness"] == "needs_detail"
    assert "배운 점과 느낀 점" in saved.json()["evidence"][0]["missing_fields"]
    flows = await client.get(
        "/api/v1/application-preparations/activity-flows", headers=owner_headers
    )
    assert flows.status_code == 200
    assert auth_headers["Authorization"] != owner_headers["Authorization"]
