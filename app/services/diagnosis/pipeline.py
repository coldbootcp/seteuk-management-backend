import asyncio
import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.diagnosis import (
    DomainFeedback,
    DomainFeedbackDraft,
    ExtractedInterestsResult,
    NarrativeReportDraft,
    PreQuestion,
    PreQuestionAnswer,
    PreQuestionsResponse,
    SemesterSummary,
    SemesterSummaryDraft,
    SynthesisResult,
)
from app.services.diagnosis.data import SemesterGroup, get_domain_rows, get_semester_groups
from app.services.diagnosis.prompts import (
    DOMAIN_FEEDBACK_SYSTEM_PROMPT,
    INTEREST_EXTRACTION_SYSTEM_PROMPT,
    NARRATIVE_REPORT_SYSTEM_PROMPT,
    PRE_QUESTION_SYSTEM_PROMPT,
    SEMESTER_SUMMARY_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
)
from app.services.llm import call_structured


async def generate_pre_questions(
    interests: dict[str, Any], seteuk_summary: dict[str, Any]
) -> list[PreQuestion]:
    user_content = json.dumps(
        {"current_interests": interests, "seteuk_summary": seteuk_summary}, ensure_ascii=False
    )
    result = await call_structured(
        PRE_QUESTION_SYSTEM_PROMPT, user_content, PreQuestionsResponse
    )
    return result.questions[:5]


async def extract_interests_from_answers(
    answers: list[PreQuestionAnswer],
) -> ExtractedInterestsResult:
    answered = [a for a in answers if a.answer]
    if not answered:
        return ExtractedInterestsResult(items=[])

    user_content = json.dumps(
        [{"key": a.key, "prompt": a.prompt, "answer": a.answer} for a in answered],
        ensure_ascii=False,
    )
    return await call_structured(
        INTEREST_EXTRACTION_SYSTEM_PROMPT, user_content, ExtractedInterestsResult
    )


async def _summarize_semester(group: SemesterGroup, interests: dict[str, Any]) -> SemesterSummary:
    user_content = json.dumps(
        {
            "grade": group.grade,
            "semester": group.semester,
            "career_context": interests,
            "data": group.to_prompt_json(),
        },
        ensure_ascii=False,
    )
    draft = await call_structured(
        SEMESTER_SUMMARY_SYSTEM_PROMPT, user_content, SemesterSummaryDraft
    )
    return SemesterSummary(
        grade=group.grade,
        semester=group.semester,
        summary=draft.summary,
        standout_activities=draft.standout_activities,
    )


async def _summarize_domain(
    domain: str, rows: list[dict[str, Any]], interests: dict[str, Any]
) -> DomainFeedback:
    user_content = json.dumps(
        {"domain": domain, "career_context": interests, "data": rows}, ensure_ascii=False
    )
    draft = await call_structured(DOMAIN_FEEDBACK_SYSTEM_PROMPT, user_content, DomainFeedbackDraft)
    return DomainFeedback(domain=domain, feedback=draft.feedback)


async def _write_narrative_report(
    synthesis: SynthesisResult, interests: dict[str, Any]
) -> str:
    """4단계 — 3단계(종합) 결과만 입력으로 받는다(원본 데이터 재조회 없음). 진단당
    1회만 호출되고 diagnoses.narrative_report에 저장되므로, 조회할 때마다 다시
    LLM을 부르지 않고 같은 문구를 돌려줄 수 있다."""
    user_content = json.dumps(
        {"career_context": interests, **synthesis.model_dump()}, ensure_ascii=False
    )
    draft = await call_structured(
        NARRATIVE_REPORT_SYSTEM_PROMPT, user_content, NarrativeReportDraft
    )
    return draft.report


async def run_diagnosis_pipeline(
    db: AsyncSession, user_id: uuid.UUID, interests: dict[str, Any]
) -> tuple[list[SemesterSummary], list[DomainFeedback], SynthesisResult, str]:
    semester_groups = await get_semester_groups(db, user_id)
    domain_rows = await get_domain_rows(db, user_id)
    non_empty_domains = [(domain, rows) for domain, rows in domain_rows.items() if rows]

    # 1단계(학기별)와 2단계(분야별)는 서로 독립적이라 함께 병렬 실행.
    semester_summaries, domain_feedback = await asyncio.gather(
        asyncio.gather(*(_summarize_semester(g, interests) for g in semester_groups)),
        asyncio.gather(
            *(_summarize_domain(domain, rows, interests) for domain, rows in non_empty_domains)
        ),
    )
    semester_summaries = list(semester_summaries)
    domain_feedback = list(domain_feedback)

    # 3단계(종합)는 원본 데이터가 아니라 1·2단계 결과만 입력으로 받는다 — 생기부를
    # 아예 안 올린 사용자(semester_summaries/domain_feedback이 비어있음)라도
    # student_interests(interests)만으로 진단이 가능해야 한다.
    synthesis_input = json.dumps(
        {
            "career_context": interests,
            "semester_summaries": [s.model_dump() for s in semester_summaries],
            "domain_feedback": [d.model_dump() for d in domain_feedback],
        },
        ensure_ascii=False,
    )
    synthesis = await call_structured(SYNTHESIS_SYSTEM_PROMPT, synthesis_input, SynthesisResult)
    narrative_report = await _write_narrative_report(synthesis, interests)

    return semester_summaries, domain_feedback, synthesis, narrative_report
