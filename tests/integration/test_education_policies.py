from datetime import UTC, datetime

from app.models.education_policy import AdmissionPolicyRule, EducationPolicy
from tests.conftest import TestSessionLocal


async def _seed_policies() -> None:
    async with TestSessionLocal() as db:
        policy_2015 = EducationPolicy(
            code="2015-revised-high-school",
            title="2015 개정 교육과정 고교생 기준",
            freshman_year_start=2018,
            freshman_year_end=2024,
            curriculum_name="2015 개정 교육과정",
            rank_grade_scale=9,
            summary="9등급제",
            details={"grade_system": "석차등급 9등급 산출"},
            source_label="공식 학생부 기준",
            source_url="https://example.edu/policy-2015",
            verified_at=datetime.now(UTC),
        )
        policy_2022 = EducationPolicy(
            code="2022-revised-high-school",
            title="2022 개정 교육과정·고교학점제 기준",
            freshman_year_start=2025,
            freshman_year_end=None,
            curriculum_name="2022 개정 교육과정",
            rank_grade_scale=5,
            summary="5등급제",
            details={"grade_system": "석차등급 5등급 산출"},
            source_label="공식 학생부 기준",
            source_url="https://example.edu/policy-2022",
            verified_at=datetime.now(UTC),
        )
        db.add_all([policy_2015, policy_2022])
        await db.flush()
        db.add_all(
            [
                AdmissionPolicyRule(
                    code="rank-scale-2022-revised",
                    policy_id=policy_2022.id,
                    category="student_record",
                    decision_scope="common",
                    title="석차등급 5등급제",
                    summary="5등급제",
                    action_required=None,
                    source_label="공식 학생부 기준",
                    source_url="https://example.edu/rank",
                    verified_at=datetime.now(UTC),
                ),
                AdmissionPolicyRule(
                    code="graduate-susi-eligibility-is-track-specific",
                    policy_id=None,
                    category="eligibility",
                    decision_scope="track_specific",
                    title="졸업생·재수생 수시 지원 자격",
                    summary="대학·전형별로 확인합니다.",
                    action_required="모집요강 확인",
                    source_label="공식 대입 기본사항",
                    source_url="https://example.edu/eligibility",
                    verified_at=datetime.now(UTC),
                ),
            ]
        )
        await db.commit()


async def test_policy_resolves_by_freshman_year_and_blocks_wrong_rank(
    client, auth_headers
) -> None:
    await _seed_policies()
    profile = {
        "name": "홍길동",
        "grade": 2,
        "semester": 1,
        "freshman_academic_year": 2025,
        "career_goal": {"goal": "공학"},
        "target_department": "컴퓨터공학과",
        "interest_keywords": ["프로그래밍"],
        "career_specificity": {"level": "broad"},
        "preferred_output_types": [],
        "activity_channels": [],
        "self_assessed_strengths": "호기심",
        "self_assessed_weaknesses": "경험 부족",
    }
    profile_response = await client.post("/api/v1/profile", json=profile, headers=auth_headers)
    assert profile_response.status_code == 200

    resolved = await client.get("/api/v1/education-policies/me", headers=auth_headers)
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["freshman_academic_year"] == 2025
    assert body["policy"]["code"] == "2022-revised-high-school"
    assert body["policy"]["rank_grade_scale"] == 5
    assert any(rule["decision_scope"] == "track_specific" for rule in body["admission_rules"])

    rejected = await client.post(
        "/api/v1/academic-performance",
        json={
            "grade": 2,
            "semester": 1,
            "category": "일반선택",
            "subject": "수학Ⅰ",
            "rank": "6",
        },
        headers=auth_headers,
    )
    assert rejected.status_code == 422
    assert rejected.json()["error_code"] == "GRADE_SCALE_MISMATCH"

    accepted = await client.post(
        "/api/v1/academic-performance",
        json={
            "grade": 2,
            "semester": 1,
            "category": "일반선택",
            "subject": "수학Ⅰ",
            "rank": "5",
        },
        headers=auth_headers,
    )
    assert accepted.status_code == 201
