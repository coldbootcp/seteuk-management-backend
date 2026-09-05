import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.services.diagnosis.pipeline as pipeline
import app.services.diagnosis_service as diagnosis_service
from app.models.activity import Activity
from app.models.activity_thread import ActivityThread
from app.schemas.diagnosis import (
    ActivityInventoryDraft,
    CareerThreadDraft,
    ExtractedInterestsResult,
    KnowledgeGraphDraft,
    OverallAssessmentDraft,
    PreQuestion,
    PreQuestionsResponse,
    SemesterReviewDraft,
)
from tests.conftest import TestSessionLocal

FAKE_CAREER_THREAD = CareerThreadDraft(
    career_thread=[
        {
            "title": "테스트 갈래",
            "summary": "테스트 활동에서 시작한 갈래입니다.",
            # 입력 activities에 붙은 정수 index. 1은 실제 활동, 99는 LLM이 지어낸
            # 값을 흉내 낸 것으로 조용히 버려져야 한다.
            "activity_indexes": [1, 99],
            "entries": [
                {
                    "grade": 1,
                    "semester": 1,
                    "type": "completed",
                    "theme": "테스트 활동",
                    "source": "활동: 테스트",
                    "connection": "다음 단계로 이어짐",
                }
            ],
        }
    ]
)


async def _fake_call_structured(system_prompt: str, user_content: str, response_model: type):
    if response_model is PreQuestionsResponse:
        return PreQuestionsResponse(
            questions=[
                PreQuestion(key="motivation", prompt="이 진로에 관심을 갖게 된 계기는?", options=[])
            ]
        )
    if response_model is ExtractedInterestsResult:
        return ExtractedInterestsResult(
            items=[{"field_key": "motivation", "value": "책을 읽고 관심이 생김"}]
        )
    if response_model is SemesterReviewDraft:
        return SemesterReviewDraft(
            grades_review="이 학기 성적 평가입니다.",
            reading_review="이 학기 독서 평가입니다.",
            activities_review="이 학기 활동 평가입니다.",
        )
    if response_model is CareerThreadDraft:
        return FAKE_CAREER_THREAD
    if response_model is ActivityInventoryDraft:
        # 배치(학년)에 실제로 들어온 index를 그대로 돌려줘야 pipeline의 역참조를
        # 통과한다 — activity_id를 직접 베끼게 하지 않는 게 이 계약의 핵심이다.
        payload = json.loads(user_content)
        return ActivityInventoryDraft(
            entries=[
                {
                    "index": a["index"],
                    "competency": "전공관련교과역량",
                    "depth_level": "탐구시도",
                    "headline": f"{a['activity_name']} 요약",
                }
                for a in payload["activities"]
            ]
        )
    if response_model is KnowledgeGraphDraft:
        # 후보 쌍을 미리 추려주지 않는다 — 전체 활동 목록을 보고 직접 판단해야
        # 하므로, 여기서도 실제 내용(과목)을 보고 링크를 결정한다.
        payload = json.loads(user_content)
        math_activities = [a for a in payload["activities"] if a["subject"] == "수학"]
        if len(math_activities) < 2:
            return KnowledgeGraphDraft(links=[])
        return KnowledgeGraphDraft(
            links=[
                {
                    "from_index": math_activities[0]["index"],
                    "to_index": math_activities[1]["index"],
                    "link_type": "vertical",
                    "relation_label": "테스트 융합",
                }
            ]
        )
    if response_model is OverallAssessmentDraft:
        return OverallAssessmentDraft(
            strengths=["강점1"],
            weaknesses=["약점1"],
            opportunities=["기회1"],
            threats=["위협1"],
            headline_comment="가장 시급한 것은 기회1입니다.",
        )
    raise AssertionError(f"unexpected response_model: {response_model}")


@pytest.fixture(autouse=True)
def _patch_session_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diagnosis_service, "AsyncSessionLocal", TestSessionLocal)


@pytest.fixture(autouse=True)
def _patch_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "call_structured", _fake_call_structured)


async def test_pre_questions_returns_questions_before_first_diagnosis(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/diagnosis/pre-questions", headers=auth_headers)

    assert response.status_code == 200
    questions = response.json()["questions"]
    assert len(questions) == 1
    assert questions[0]["key"] == "motivation"


async def test_diagnosis_end_to_end(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    # 성적 추이 섹션은 LLM 없이 원자료를 그대로 재구성하므로, 실제로 그렇게
    # 동작하는지 확인하려면 academic_performance가 있어야 한다. 등급이 매겨진 과목
    # 둘과 매겨지지 않은 과목 하나를 섞어, 평균이 앞의 둘로만 계산되는지 본다.
    for payload in (
        {"subject": "수학", "category": "수학", "achievement_grade": "A", "rank": "2"},
        {"subject": "영어", "category": "영어", "achievement_grade": "B", "rank": "4"},
        # 진로선택과목 — 성취도만 있고 석차등급이 없다.
        {"subject": "공학 일반", "category": "기술·가정", "achievement_grade": "A"},
    ):
        await client.post(
            "/api/v1/academic-performance",
            json={"grade": 1, "semester": 1, "raw_score": 95, **payload},
            headers=auth_headers,
        )

    # 같은 과목·다른 학기 활동 두 개 — 지식 그래프 fake가 내용(과목)을 보고
    # 이 둘을 링크로 찾아내는지 확인하기 위함이다.
    activity_a = (
        await client.post(
            "/api/v1/activities",
            json={
                "grade": 1,
                "semester": 1,
                "activity_category": "과목세부특기사항",
                "subject": "수학",
                "activity_name": "지수함수 기초 탐구",
                "activity_type": "report",
                "description": "지수함수의 기본 성질을 탐구함.",
                "keywords": ["로봇"],
            },
            headers=auth_headers,
        )
    ).json()
    activity_b = (
        await client.post(
            "/api/v1/activities",
            json={
                "grade": 2,
                "semester": 1,
                "activity_category": "과목세부특기사항",
                "subject": "수학",
                "activity_name": "로지스틱 함수 심화 탐구",
                "activity_type": "report",
                "description": "지수함수의 한계를 로지스틱 함수로 보완함.",
                "keywords": ["로봇"],
            },
            headers=auth_headers,
        )
    ).json()

    answers_response = await client.post(
        "/api/v1/diagnosis/pre-questions/answers",
        headers=auth_headers,
        json={
            "answers": [
                {"key": "motivation", "prompt": "계기는?", "answer": "책을 읽고 관심이 생김"}
            ]
        },
    )
    assert answers_response.status_code == 204

    create_response = await client.post("/api/v1/diagnosis", headers=auth_headers)
    assert create_response.status_code == 201
    diagnosis_id = create_response.json()["diagnosis_id"]
    assert create_response.json()["status"] == "processing"

    result_response = await client.get(f"/api/v1/diagnosis/{diagnosis_id}", headers=auth_headers)
    assert result_response.status_code == 200
    body = result_response.json()
    assert body["status"] == "done"

    # 성적 추이 — LLM 없이 원자료에서 직접 계산된다. 과목별 선은 그리지 않고
    # 학기별 평균 석차등급 한 줄만 낸다.
    assert "subjects" not in body["grades_trend"]
    point = body["grades_trend"]["overall"][0]
    assert (point["grade"], point["semester"]) == (1, 1)
    # 석차등급이 있는 두 과목(2, 4)만 평균에 들어간다.
    assert point["average_rank"] == 3.0
    assert point["subject_count"] == 2
    # 등급이 없어 빠진 과목이 몇 개인지 함께 밝힌다 — 안 그러면 평균이 그 학기
    # 전체를 대표하는 것처럼 읽힌다.
    assert point["excluded_count"] == 1

    # 학기별 평가 — 3개의 독립된 텍스트로 나뉘어 저장된다.
    review = body["semester_reviews"][0]
    assert review["grade"] == 1 and review["semester"] == 1
    assert review["grades_review"] == "이 학기 성적 평가입니다."
    assert review["reading_review"] == "이 학기 독서 평가입니다."
    assert review["activities_review"] == "이 학기 활동 평가입니다."

    # 진로 유기적 평가
    # 진로 사슬은 주제별 갈래로 묶인다 — 시간순 평면 배열이 아니다.
    thread = body["career_thread"][0]
    assert thread["title"] == "테스트 갈래"
    assert thread["entries"][0]["theme"] == "테스트 활동"

    # 활동 인벤토리 — 필터링 없이 활동 2개 전량에 분류가 매겨진다.
    inventory_ids = {e["activity_id"] for e in body["activity_inventory"]}
    assert inventory_ids == {activity_a["id"], activity_b["id"]}
    assert all(e["competency"] == "전공관련교과역량" for e in body["activity_inventory"])

    # 지식 그래프 — 같은 과목이라 내용 기반으로 링크가 하나 확정된다.
    assert len(body["knowledge_graph_links"]) == 1
    link = body["knowledge_graph_links"][0]
    assert {link["from_activity_id"], link["to_activity_id"]} == {
        activity_a["id"],
        activity_b["id"],
    }
    assert link["link_type"] == "vertical"

    # 종합 평가(SWOT) — 4개의 독립 필드 + 헤드라인.
    assert body["strengths"] == ["강점1"]
    assert body["weaknesses"] == ["약점1"]
    assert body["opportunities"] == ["기회1"]
    assert body["threats"] == ["위협1"]
    assert body["headline_comment"] == "가장 시급한 것은 기회1입니다."

    latest_response = await client.get("/api/v1/diagnosis/latest", headers=auth_headers)
    assert latest_response.json()["diagnosis_id"] == diagnosis_id


async def test_diagnosis_works_without_any_seteuk_data(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """생기부를 아예 안 올린 사용자도 진단이 실패하지 않아야 한다 — 종합 평가는
    학기별 평가/진로 사슬/활동 인벤토리가 비어 있어도 예외 없이 호출된다."""
    create_response = await client.post("/api/v1/diagnosis", headers=auth_headers)
    diagnosis_id = create_response.json()["diagnosis_id"]

    result_response = await client.get(f"/api/v1/diagnosis/{diagnosis_id}", headers=auth_headers)
    body = result_response.json()
    assert body["status"] == "done"
    assert body["semester_reviews"] == []
    assert body["grades_trend"] == {"overall": []}
    assert body["activity_inventory"] == []
    assert body["knowledge_graph_links"] == []
    assert body["strengths"] == ["강점1"]


async def test_pre_questions_empty_after_first_diagnosis(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    create_response = await client.post("/api/v1/diagnosis", headers=auth_headers)
    diagnosis_id = create_response.json()["diagnosis_id"]
    await client.get(f"/api/v1/diagnosis/{diagnosis_id}", headers=auth_headers)

    response = await client.get("/api/v1/diagnosis/pre-questions", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["questions"] == []


async def test_diagnosis_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/api/v1/diagnosis")

    assert response.status_code == 401


async def test_threads_are_persisted_and_linked_to_activities(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """진로 사슬은 진단 출력으로만 끝나지 않고 activity_threads에 남고 활동에
    thread_id가 붙는다 — 갈래는 지속되는 구조라야 이후 지식 그래프·챗봇이 "같은
    갈래인가"를 물을 수 있다."""
    created = await client.post(
        "/api/v1/activities",
        json={
            "grade": 1,
            "semester": 1,
            "activity_category": "과목세부특기사항",
            "activity_name": "테스트",
            "activity_type": "report",
            "description": "설명",
        },
        headers=auth_headers,
    )
    activity_id = created.json()["id"]

    diagnosis_id = (
        await client.post("/api/v1/diagnosis", headers=auth_headers)
    ).json()["diagnosis_id"]
    await client.get(f"/api/v1/diagnosis/{diagnosis_id}", headers=auth_headers)

    async with TestSessionLocal() as db:
        threads = list(await db.scalars(select(ActivityThread)))
        assert [t.title for t in threads] == ["테스트 갈래"]

        activity = await db.get(Activity, uuid.UUID(activity_id))
        # index 1은 실제 활동이라 연결되고, LLM이 지어낸 99는 조용히 버려진다.
        assert activity.thread_id == threads[0].id
