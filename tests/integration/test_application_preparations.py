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


@pytest.mark.asyncio
async def test_resaving_the_same_evidence_does_not_conflict(client, auth_headers) -> None:
    """실제 UI 검증에서 발견: 'AI가 핵심 활동 추리기'가 추천 근거를 자동 저장한 직후
    학생이 '설계 저장'을 눌러 같은 활동을 다시 저장하면, 삭제-삽입이 같은
    (preparation_id, activity_id) 쌍을 다시 쓰면서 uq_application_evidence_activity
    위반으로 500이 났다."""
    university = University(official_code="test-u2", name="테스트대학교2", source_url="https://example.edu")
    async with TestSessionLocal() as db:
        db.add(university)
        await db.flush()
        program = AdmissionProgram(
            university_id=university.id,
            admission_year=2027,
            name="테스트학과2",
            source_url="https://example.edu/2027",
        )
        db.add(program)
        await db.commit()

    signup = await client.post(
        "/api/v1/auth/signup",
        json={"email": "resave-owner@example.com", "password": "s3cure-passw0rd"},
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
    preparation_id = created.json()["id"]
    body = {
        "central_question": None,
        "narrative_outline": [],
        "evidence": [
            {"activity_id": activity.json()["id"], "narrative_role": "origin", "order_index": 1}
        ],
    }
    first = await client.put(
        f"/api/v1/application-preparations/{preparation_id}", headers=owner_headers, json=body
    )
    second = await client.put(
        f"/api/v1/application-preparations/{preparation_id}", headers=owner_headers, json=body
    )
    assert first.status_code == 200
    assert second.status_code == 200
