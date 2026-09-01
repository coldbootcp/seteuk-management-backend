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


async def test_roadmap_overview_survives_year_level_completed_nodes(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """자율활동/진로활동처럼 학기 없이 학년 단위로만 기록된 근거를 든 completed
    노드는 career_thread.semester가 null일 수 있다(실제 DeepSeek 응답에서 발생해
    진단 전체가 실패했던 버그). None과 int가 같은 학년 안에 섞여도 정렬이
    깨지지 않아야 하고, semester가 없는 suggested 노드는 마일스톤에서 조용히
    빠져야 한다."""
    await _onboard(client, auth_headers)
    async with TestSessionLocal() as db:
        user = await db.scalar(
            select(User).where(User.email == "seteuk-tester@example.com")
        )
        diagnosis = Diagnosis(
            user_id=user.id,
            status=DiagnosisStatus.DONE.value,
            career_thread=[
                {
                    "grade": 1,
                    "semester": None,
                    "type": "completed",
                    "theme": "자율활동 기반 리더십",
                    "source": "자율활동: 학급자치회장",
                    "connection": "학기 활동으로 이어짐",
                },
                {
                    "grade": 1,
                    "semester": 2,
                    "type": "completed",
                    "theme": "로봇 입문",
                    "source": "활동: 로봇 제작 동아리",
                    "connection": "다음 단계로 이어짐",
                },
                {
                    "grade": 2,
                    "semester": None,
                    "type": "suggested",
                    "theme": "학기를 특정할 수 없는 제안",
                    "source": None,
                    "connection": "…",
                },
            ],
            weaknesses=[],
            headline_comment=None,
        )
        db.add(diagnosis)
        await db.commit()

    response = await client.get("/api/v1/plans/roadmap-overview", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()

    # 학년 안에서 semester=None인 노드가 int 노드와 섞여도 깨지지 않고, 정렬
    # 목적으로 맨 앞에 온다.
    assert body["past"] == [
        {
            "grade": 1,
            "summary": "자율활동 기반 리더십 → 로봇 입문",
            "themes": ["자율활동 기반 리더십", "로봇 입문"],
        }
    ]
    # semester가 없는 suggested 노드는 마일스톤으로 배치할 수 없으므로 제외된다.
    assert body["future"] == []
