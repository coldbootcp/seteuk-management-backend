import pytest
from httpx import AsyncClient

import app.services.diagnosis.pipeline as pipeline
import app.services.diagnosis_service as diagnosis_service
from app.schemas.diagnosis import (
    DomainFeedbackDraft,
    ExtractedInterestsResult,
    NarrativeReportDraft,
    PreQuestion,
    PreQuestionsResponse,
    SemesterSummaryDraft,
    SynthesisResult,
)
from tests.conftest import TestSessionLocal

FAKE_SYNTHESIS = SynthesisResult(
    career_thread=[
        {
            "grade": 1,
            "semester": 1,
            "type": "completed",
            "theme": "테스트 활동",
            "source": "활동: 테스트",
            "connection": "다음 단계로 이어짐",
        }
    ],
    overall_summary="종합 요약입니다.",
    strengths=["강점1"],
    weaknesses=["약점1"],
    career_gap_analysis="갭 분석입니다.",
    keyword_map=["키워드1"],
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
    if response_model is SemesterSummaryDraft:
        return SemesterSummaryDraft(summary="이 학기 요약입니다.", standout_activities=["활동A"])
    if response_model is DomainFeedbackDraft:
        return DomainFeedbackDraft(feedback="이 분야에서는 이런 점이 좋았습니다.")
    if response_model is SynthesisResult:
        return FAKE_SYNTHESIS
    if response_model is NarrativeReportDraft:
        return NarrativeReportDraft(report="챗봇 말투로 풀어쓴 리포트입니다.")
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
    assert body["overall_summary"] == "종합 요약입니다."
    assert body["career_thread"][0]["theme"] == "테스트 활동"
    # 4단계 — 구조화 필드와 별개로 챗봇 말투 리포트도 함께 저장/반환된다.
    assert body["narrative_report"] == "챗봇 말투로 풀어쓴 리포트입니다."

    latest_response = await client.get("/api/v1/diagnosis/latest", headers=auth_headers)
    assert latest_response.json()["diagnosis_id"] == diagnosis_id


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
