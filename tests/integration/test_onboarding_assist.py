from types import SimpleNamespace

import pytest
from httpx import AsyncClient

import app.services.profile_service as profile_service
import app.services.roadmap_service as roadmap_service
from app.schemas.profile import ClarifyResponse, SuggestResponse
from app.schemas.roadmap import NodeSummaryDraft

CAPTURED: dict[str, str] = {}


async def _fake_call(system_prompt: str, user_content: str, response_model: type):
    CAPTURED["user_content"] = user_content
    if response_model is SuggestResponse:
        return SuggestResponse(
            majors=["산업공학과", "컴퓨터공학과"], keywords=["데이터 기반 문제 해결"]
        )
    if response_model is ClarifyResponse:
        return ClarifyResponse(
            questions=[
                {
                    "key": "career_resolution",
                    "label": "진로 확신도",
                    "question": "이 진로에 대한 확신은 어느 정도인가요?",
                    "why": "로드맵을 얼마나 좁게 잡을지가 여기서 갈립니다.",
                    "selection_mode": "single",
                    "options": ["확실하다", "고민 중이다"],
                }
            ]
        )
    if response_model is NodeSummaryDraft:
        return NodeSummaryDraft(summary="이 학기는 데이터 분석 갈래로 채워졌습니다.")
    raise AssertionError(f"unexpected response_model: {response_model}")


@pytest.fixture(autouse=True)
def _patch_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profile_service, "call_structured", _fake_call)
    monkeypatch.setattr(roadmap_service, "call_structured", _fake_call)


async def test_suggest_offers_candidates_without_saving_anything(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """제안은 제안일 뿐이다 — 학생이 고른 값만 POST /profile로 확정된다."""
    response = await client.post(
        "/api/v1/profile/suggest", json={"career_goal": "데이터 기반 연구직"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert "산업공학과" in response.json()["majors"]

    # 프로필은 여전히 비어 있다.
    profile = await client.get("/api/v1/profile/me", headers=auth_headers)
    assert profile.json()["target_department"] is None


async def test_clarify_asks_about_what_is_still_missing(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/profile/clarify",
        json={"name": "홍길동", "grade": 2, "career_goal": "연구직"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    question = response.json()["questions"][0]
    assert question["selection_mode"] == "single"
    # 왜 묻는지가 함께 온다 — 학생이 답할 이유를 알아야 성의껏 답한다.
    assert question["why"]
    # 지금까지 채운 값이 프롬프트에 실제로 실린다.
    assert "홍길동" in CAPTURED["user_content"]


async def test_node_summary_uses_only_that_semesters_activities(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """활성 마디라고 해서 관련 없는 활동까지 끌어오면 근거 없는 요약이 된다."""
    await client.post(
        "/api/v1/profile",
        json={
            "name": "홍길동",
            "grade": 2,
            "semester": 1,
            "career_goal": {"goal": "연구원"},
            "target_department": "산업공학과",
            "interest_keywords": [],
            "career_specificity": {"level": "broad"},
            "preferred_output_types": [],
            "activity_channels": [],
            "self_assessed_strengths": "x",
            "self_assessed_weaknesses": "y",
        },
        headers=auth_headers,
    )
    for grade, semester, name in ((2, 1, "이번 학기 활동"), (1, 1, "지난 학기 활동")):
        await client.post(
            "/api/v1/activities",
            json={
                "grade": grade,
                "semester": semester,
                "activity_category": "과목세부특기사항",
                "activity_name": name,
                "activity_type": "report",
                "description": "설명",
            },
            headers=auth_headers,
        )

    roadmap = (await client.post("/api/v1/roadmaps", json={}, headers=auth_headers)).json()
    node = next(n for n in roadmap["nodes"] if (n["grade"], n["semester"]) == (2, 1))

    response = await client.post(
        f"/api/v1/roadmaps/nodes/{node['id']}/summarize", headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["summary"]

    assert "이번 학기 활동" in CAPTURED["user_content"]
    assert "지난 학기 활동" not in CAPTURED["user_content"]


async def test_clarify_stops_asking_once_enough_answers_are_in(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """질문을 몇 번 더 낼지는 모델에게 맡기지 않는다. "충분하면 그만 물어라"라고
    부탁해도 계속 새 질문을 만들어 내는 것을 관측했고, 그러면 학생이 온보딩에서
    빠져나오지 못한다."""

    async def _always_asks(system_prompt: str, user_content: str, response_model: type):
        raise AssertionError("상한을 넘었으면 LLM을 부르지 않아야 한다")

    monkeypatch.setattr(profile_service, "call_structured", _always_asks)

    response = await client.post(
        "/api/v1/profile/clarify",
        json={
            "career_goal": "연구직",
            "answers": [
                {"key": f"q{index}", "question": "…", "answer": "…"} for index in range(6)
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json() == {"questions": [], "complete": True}


async def test_clarify_marks_itself_complete_when_it_has_nothing_left_to_ask(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _no_questions(system_prompt: str, user_content: str, response_model: type):
        return ClarifyResponse(questions=[])

    monkeypatch.setattr(profile_service, "call_structured", _no_questions)

    response = await client.post(
        "/api/v1/profile/clarify", json={"career_goal": "연구직"}, headers=auth_headers
    )
    assert response.json()["complete"] is True


async def test_clarify_drops_nonessential_and_out_of_scale_questions_for_5_grade_students(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """입학 연도와 맞지 않는 성적 질문은 프롬프트를 어겨도 화면까지 오면 안 된다."""

    async def _bad_questions(system_prompt: str, user_content: str, response_model: type):
        return ClarifyResponse(
            questions=[
                {
                    "key": "current_grade_level",
                    "label": "현재 성적 수준",
                    "question": (
                        "현재 이수 중인 수학, 물리, 화학 과목에서 "
                        "어느 정도의 성적을 받고 있나요?"
                    ),
                    "why": "학습 수준을 보려 합니다.",
                    "selection_mode": "single",
                    "options": ["상위권 (1~2등급)", "중상위권 (3~4등급)", "중위권 (5~6등급)"],
                },
                {
                    "key": "rank_scale_error",
                    "label": "등급 선택",
                    "question": "앞으로 지키고 싶은 학습 목표는 무엇인가요?",
                    "why": "계획을 세우려 합니다.",
                    "selection_mode": "single",
                    "options": ["1~2등급", "5~6등급"],
                },
                {
                    "key": "school_programs",
                    "label": "학교 프로그램",
                    "question": "이번 학기에 참여할 동아리나 대회가 있나요?",
                    "why": "활동 계획을 세우려 합니다.",
                    "selection_mode": "single",
                    "options": ["동아리", "대회", "아직 없음"],
                },
            ]
        )

    async def _five_grade_policy(*_args, **_kwargs):
        return SimpleNamespace(rank_grade_scale=5)

    monkeypatch.setattr(profile_service, "call_structured", _bad_questions)
    monkeypatch.setattr(profile_service, "get_policy_for_freshman_year", _five_grade_policy)

    response = await client.post(
        "/api/v1/profile/clarify",
        json={"freshman_academic_year": 2026, "career_goal": "반도체 공학"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {"questions": [], "complete": True}


async def test_clarify_skips_llm_when_student_already_has_a_direction(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """기본 진로 축을 받은 뒤에는 별도 확인 단계로 되돌아가지 않는다."""

    async def _should_not_call_llm(*_args, **_kwargs):
        raise AssertionError("진로 축이 충분하면 확인 질문용 LLM을 호출하면 안 된다")

    monkeypatch.setattr(profile_service, "call_structured", _should_not_call_llm)

    response = await client.post(
        "/api/v1/profile/clarify",
        json={
            "freshman_academic_year": 2026,
            "career_goal": "반도체 공학",
            "target_department": "반도체공학과",
            "interest_keywords": ["반도체 소자", "집적회로"],
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {"questions": [], "complete": True}
