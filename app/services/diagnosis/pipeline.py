import asyncio
import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.diagnosis import (
    CareerThreadDraft,
    CareerThreadEntry,
    ExtractedInterestsResult,
    GradesTrend,
    OverallAssessmentDraft,
    PreQuestion,
    PreQuestionAnswer,
    PreQuestionsResponse,
    SemesterReview,
    SemesterReviewDraft,
)
from app.services.diagnosis.data import (
    SemesterGroup,
    compute_grades_trend,
    get_career_thread_material,
    get_semester_groups,
)
from app.services.diagnosis.prompts import (
    CAREER_THREAD_SYSTEM_PROMPT,
    INTEREST_EXTRACTION_SYSTEM_PROMPT,
    OVERALL_ASSESSMENT_SYSTEM_PROMPT,
    PRE_QUESTION_SYSTEM_PROMPT,
    SEMESTER_REVIEW_SYSTEM_PROMPT,
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


async def _review_semester(group: SemesterGroup, interests: dict[str, Any]) -> SemesterReview:
    """학기별 평가 — 그 학기의 성적/독서/활동 원자료만 입력으로 받는다. LLM은
    이 좁은 자료를 세 개의 구체적인 문장으로 옮기는 번역기 역할만 한다."""
    user_content = json.dumps(
        {
            "grade": group.grade,
            "semester": group.semester,
            "career_context": interests,
            "data": group.to_prompt_json(),
        },
        ensure_ascii=False,
    )
    draft = await call_structured(SEMESTER_REVIEW_SYSTEM_PROMPT, user_content, SemesterReviewDraft)
    return SemesterReview(
        grade=group.grade,
        semester=group.semester,
        grades_review=draft.grades_review,
        reading_review=draft.reading_review,
        activities_review=draft.activities_review,
    )


async def _write_career_thread(
    material: dict[str, Any], interests: dict[str, Any], current_grade: int | None,
    current_semester: int | None,
) -> list[CareerThreadEntry]:
    """진로 유기적 평가 — 활동/수상/봉사 전체를 입력받아, 진로 관점에서 의미 있는
    것만 사슬로 엮는다. 학기별 평가와 달리 전체 이력을 한 번에 봐야 '연결'을
    판단할 수 있으므로 학기 단위로 쪼개지 않는다."""
    user_content = json.dumps(
        {
            "career_context": interests,
            "current_grade": current_grade,
            "current_semester": current_semester,
            **material,
        },
        ensure_ascii=False,
    )
    draft = await call_structured(CAREER_THREAD_SYSTEM_PROMPT, user_content, CareerThreadDraft)
    return draft.career_thread


async def _write_overall_assessment(
    semester_reviews: list[SemesterReview], career_thread: list[CareerThreadEntry]
) -> OverallAssessmentDraft:
    """종합 평가 — 원본 데이터가 아니라 학기별 평가와 진로 유기적 평가의 "결과"만
    입력으로 받는다. 생기부를 아예 안 올린 사용자(둘 다 비어있음)라도 예외 없이
    호출되므로, 프롬프트가 빈 입력에도 정직하게 답하도록 규칙에 명시돼 있다."""
    user_content = json.dumps(
        {
            "semester_reviews": [s.model_dump() for s in semester_reviews],
            "career_thread": [t.model_dump() for t in career_thread],
        },
        ensure_ascii=False,
    )
    return await call_structured(
        OVERALL_ASSESSMENT_SYSTEM_PROMPT, user_content, OverallAssessmentDraft
    )


async def run_diagnosis_pipeline(
    db: AsyncSession, user_id: uuid.UUID, interests: dict[str, Any]
) -> tuple[GradesTrend, list[SemesterReview], list[CareerThreadEntry], OverallAssessmentDraft]:
    user = await db.get(User, user_id)

    semester_groups = await get_semester_groups(db, user_id)
    career_material = await get_career_thread_material(db, user_id)

    # 성적 추이(LLM 없음)·학기별 평가·진로 유기적 평가는 서로 입력이 겹치지 않는
    # 독립 섹션이라 함께 병렬 실행한다.
    grades_trend, semester_reviews, career_thread = await asyncio.gather(
        compute_grades_trend(db, user_id),
        asyncio.gather(*(_review_semester(g, interests) for g in semester_groups)),
        _write_career_thread(
            career_material,
            interests,
            user.current_grade if user else None,
            user.current_semester if user else None,
        ),
    )
    semester_reviews = list(semester_reviews)

    # 종합 평가는 위 두 섹션의 결과만 보고 판단한다 — 원본 데이터를 다시 훑지 않는다.
    overall = await _write_overall_assessment(semester_reviews, career_thread)

    return grades_trend, semester_reviews, career_thread, overall
