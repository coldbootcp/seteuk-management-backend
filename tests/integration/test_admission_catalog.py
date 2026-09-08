import pytest

from app.models.admission_catalog import AdmissionProgram, AdmissionTrack, University
from app.models.admission_program_reference import AdmissionProgramReference
from app.models.admission_university_guide import AdmissionUniversityGuide
from tests.conftest import TestSessionLocal


@pytest.mark.asyncio
async def test_catalog_follows_university_program_track_order(client, auth_headers) -> None:
    university = University(
        official_code="official-seoul",
        name="서울예시대학교",
        campus_name="본교",
        region="서울",
        source_url="https://example.edu/admissions",
    )
    async with TestSessionLocal() as db:
        db.add(university)
        await db.flush()
        program = AdmissionProgram(
            university_id=university.id,
            admission_year=2027,
            name="반도체공학과",
            college_name="공과대학",
            source_url="https://example.edu/admissions/2027",
            source_status="plan",
        )
        db.add(program)
        await db.flush()
        db.add(
            AdmissionTrack(
                program_id=program.id,
                name="학생부종합전형",
                admission_type="학생부종합",
                recruitment_period="수시",
                has_document_review=True,
                has_interview=True,
                has_minimum_requirement=False,
                source_url="https://example.edu/admissions/2027",
                source_status="plan",
            )
        )
        await db.commit()

    universities = await client.get(
        "/api/v1/admission-catalog/universities?q=서", headers=auth_headers
    )
    assert universities.status_code == 200
    assert universities.json()[0]["name"] == "서울예시대학교"
    university_id = universities.json()[0]["id"]

    programs = await client.get(
        f"/api/v1/admission-catalog/universities/{university_id}/programs?admission_year=2027&q=반도체",
        headers=auth_headers,
    )
    assert programs.status_code == 200
    assert programs.json()[0]["name"] == "반도체공학과"
    assert programs.json()[0]["source_status"] == "plan"

    tracks = await client.get(
        f"/api/v1/admission-catalog/programs/{programs.json()[0]['id']}/tracks",
        headers=auth_headers,
    )
    assert tracks.status_code == 200
    assert tracks.json()[0]["has_interview"] is True
    assert tracks.json()[0]["has_document_review"] is True
    assert tracks.json()[0]["has_minimum_requirement"] is False


@pytest.mark.asyncio
async def test_catalog_search_requires_sign_in(client) -> None:
    response = await client.get("/api/v1/admission-catalog/universities?q=서")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_catalog_returns_latest_guide_and_exact_program_profile(client, auth_headers) -> None:
    university = University(
        official_code="official-guide",
        name="가이드예시대학교",
        source_url="https://example.edu/admissions",
    )
    async with TestSessionLocal() as db:
        db.add(university)
        await db.flush()
        program = AdmissionProgram(
            university_id=university.id,
            admission_year=2027,
            name="전자공학부(주간)",
            source_url="https://example.edu/admissions/2027",
            source_status="plan",
        )
        db.add(program)
        await db.flush()
        track = AdmissionTrack(
            program_id=program.id,
            name="학생부종합전형 > 일반",
            source_url="https://example.edu/admissions/2027",
            source_status="plan",
        )
        guide = AdmissionUniversityGuide(
            university_id=university.id,
            source_admission_year=2026,
            source_url="https://example.edu/admissions/2026",
            sections=[
                {
                    "title": "입시가이드",
                    "paragraphs": ["학생부를 종합 평가합니다."],
                    "tables": [{"rows": [["구분", "반영방법"], ["서류", "100"]]}],
                }
            ],
        )
        latest_partial_guide = AdmissionUniversityGuide(
            university_id=university.id,
            source_admission_year=2027,
            source_url="https://example.edu/admissions/2027",
            sections=[
                {
                    "title": "수시 대입특징",
                    "paragraphs": ["2027학년도 수시 변화입니다."],
                    "tables": [],
                }
            ],
        )
        reference = AdmissionProgramReference(
            university_id=university.id,
            source_admission_year=2026,
            source_reference_code="guide-program",
            name="전자공학부",
            source_url="https://example.edu/program/2026",
            detail_sections=[
                {"title": "교육목표", "items": ["전자 시스템의 기초와 응용을 배웁니다."]},
                {"title": "진로취업분야", "items": ["반도체 설계", "통신"]},
            ],
        )
        db.add_all([track, guide, latest_partial_guide, reference])
        await db.commit()

    guide_response = await client.get(
        f"/api/v1/admission-catalog/universities/{university.id}/admission-guide",
        headers=auth_headers,
    )
    assert guide_response.status_code == 200
    assert guide_response.json()["source_admission_year"] == 2027
    guide_sections = guide_response.json()["sections"]
    assert guide_sections[0]["paragraphs"] == ["2027학년도 수시 변화입니다."]
    assert guide_sections[0]["source_admission_year"] == 2027
    assert guide_sections[1]["tables"][0]["rows"][1] == ["서류", "100"]
    assert guide_sections[1]["source_admission_year"] == 2026

    profile_response = await client.get(
        f"/api/v1/admission-catalog/tracks/{track.id}/program-profile",
        headers=auth_headers,
    )
    assert profile_response.status_code == 200
    assert profile_response.json()["reference_program_name"] == "전자공학부"
    assert profile_response.json()["sections"][1]["items"] == ["반도체 설계", "통신"]
