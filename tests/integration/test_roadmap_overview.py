from httpx import AsyncClient
from sqlalchemy import select

from app.models.diagnosis import Diagnosis, DiagnosisStatus
from app.models.user import User
from tests.conftest import TestSessionLocal


async def _onboard(client: AsyncClient, headers: dict[str, str]) -> None:
    await client.post(
        "/api/v1/profile",
        json={
            "name": "홍길동",
            "grade": 2,
            "semester": 1,
            "career_goal": {"goal": "로봇공학자"},
            "target_department": "기계공학과",
            "interest_keywords": ["로봇"],
            "career_specificity": {"level": "specific"},
            "preferred_output_types": ["report"],
            "activity_channels": ["동아리"],
            "self_assessed_strengths": "설계에 강함",
            "self_assessed_weaknesses": "독서가 부족함",
        },
        headers=headers,
    )


async def _seed_diagnosis(email: str) -> None:
    """새 LLM 호출 없이 조립만 하는 엔드포인트를 검증하는 것이므로, 진단 결과는
    파이프라인을 돌리지 않고 DB에 직접 심는다."""
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == email))
        diagnosis = Diagnosis(
            user_id=user.id,
            status=DiagnosisStatus.DONE.value,
            career_thread=[
                {
                    "grade": 1,
                    "semester": 1,
                    "type": "completed",
                    "theme": "기초 다지기",
                    "source": "활동: 기초 실험",
                    "connection": "다음 단계로 이어짐",
                },
                {
                    "grade": 1,
                    "semester": 2,
                    "type": "completed",
                    "theme": "로봇 입문",
                    "source": "활동: 로봇 제작 동아리",
                    "connection": "2학년 심화로 이어짐",
                },
                {
                    "grade": 2,
                    "semester": 2,
                    "type": "suggested",
                    "theme": "SIR 모델 심화",
                    "source": None,
                    "connection": "지금까지의 흐름을 심화",
                },
            ],
            weaknesses=["독서 기록 부족"],
            headline_comment="가장 시급한 것은 독서 기록 부족입니다.",
        )
        db.add(diagnosis)
        await db.commit()


async def test_roadmap_overview_assembles_past_current_future(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _onboard(client, auth_headers)
    await _seed_diagnosis("seteuk-tester@example.com")

    await client.post(
        "/api/v1/plans",
        json={
            "item_type": "activity",
            "title": "SIR 모델 시뮬레이션",
            "target_grade": 2,
            "target_semester": 2,
        },
        headers=auth_headers,
    )

    response = await client.get("/api/v1/plans/roadmap-overview", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()

    # 과거 — 완료 노드를 학년별로 묶어 한 줄 요약을 만든다.
    assert body["past"] == [
        {"grade": 1, "summary": "기초 다지기 → 로봇 입문", "themes": ["기초 다지기", "로봇 입문"]}
    ]

    # 현재 — 사용자 학년/학기 + 진단의 headline_comment/weaknesses를 그대로 가져온다.
    assert body["current"] == {
        "grade": 2,
        "semester": 1,
        "headline_comment": "가장 시급한 것은 독서 기록 부족입니다.",
        "weaknesses": ["독서 기록 부족"],
    }

    # 미래 — suggested 노드의 theme과 그 학기에 배정된 계획 제목이 합쳐진다.
    assert body["future"] == [
        {
            "grade": 2,
            "semester": 2,
            "theme": "SIR 모델 심화",
            "plan_titles": ["SIR 모델 시뮬레이션"],
        }
    ]


async def test_roadmap_overview_without_diagnosis_still_shows_plans(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """진단을 아직 안 돌렸어도 계획만으로 미래 마일스톤은 보여야 한다."""
    await _onboard(client, auth_headers)
    await client.post(
        "/api/v1/plans",
        json={
            "item_type": "reading",
            "title": "미리 세운 계획",
            "target_grade": 2,
            "target_semester": 2,
        },
        headers=auth_headers,
    )

    response = await client.get("/api/v1/plans/roadmap-overview", headers=auth_headers)
    body = response.json()

    assert body["past"] == []
    assert body["current"] == {
        "grade": 2,
        "semester": 1,
        "headline_comment": None,
        "weaknesses": [],
    }
    assert body["future"] == [
        {"grade": 2, "semester": 2, "theme": None, "plan_titles": ["미리 세운 계획"]}
    ]
