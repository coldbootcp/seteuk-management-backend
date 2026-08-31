import asyncio
import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.diagnosis import (
    ActivityInventoryDraft,
    ActivityInventoryEntry,
    CareerThreadDraft,
    CareerThreadEntry,
    ExtractedInterestsResult,
    GradesTrend,
    KnowledgeGraphDraft,
    KnowledgeGraphLink,
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
    generate_fusion_candidates,
    get_activities_by_grade,
    get_career_thread_material,
    get_semester_groups,
)
from app.services.diagnosis.prompts import (
    ACTIVITY_INVENTORY_SYSTEM_PROMPT,
    CAREER_THREAD_SYSTEM_PROMPT,
    INTEREST_EXTRACTION_SYSTEM_PROMPT,
    KNOWLEDGE_GRAPH_SYSTEM_PROMPT,
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


async def _classify_activity_batch(
    grade: int, activities: list[Any], interests: dict[str, Any]
) -> list[ActivityInventoryEntry]:
    """활동 인벤토리 — 학년 단위 배치 호출. 진로 유기적 평가와 달리 필터링하지
    않고 입력된 활동 전량에 분류를 매긴다."""
    payload = [
        {
            "id": str(a.id),
            "grade": a.grade,
            "semester": a.semester,
            "activity_category": a.activity_category,
            "subject": a.subject,
            "activity_name": a.activity_name,
            "description": a.description,
            "keywords": a.keywords,
        }
        for a in activities
    ]
    user_content = json.dumps(
        {"grade": grade, "career_context": interests, "activities": payload}, ensure_ascii=False
    )
    draft = await call_structured(
        ACTIVITY_INVENTORY_SYSTEM_PROMPT, user_content, ActivityInventoryDraft
    )
    # LLM이 존재하지 않는 id를 지어내거나 빠뜨릴 수 있으므로, 실제 배치에 있던
    # activity_id만 남긴다.
    known_ids = {a.id for a in activities}
    return [entry for entry in draft.entries if entry.activity_id in known_ids]


async def _write_knowledge_graph(
    candidates: list[Any], interests: dict[str, Any]
) -> list[KnowledgeGraphLink]:
    """지식 그래프 — 과목/키워드 겹침으로 이미 좁혀진 후보 쌍만 LLM에 준다.
    후보가 하나도 없으면 호출 자체를 건너뛴다(빈 배열은 정상 상태)."""
    if not candidates:
        return []

    known_ids = {c.activity_a.id for c in candidates} | {c.activity_b.id for c in candidates}
    user_content = json.dumps(
        {
            "career_context": interests,
            "candidates": [c.to_prompt_json() for c in candidates],
        },
        ensure_ascii=False,
    )
    draft = await call_structured(KNOWLEDGE_GRAPH_SYSTEM_PROMPT, user_content, KnowledgeGraphDraft)
    return [
        link
        for link in draft.links
        if link.from_activity_id in known_ids and link.to_activity_id in known_ids
    ]


async def _write_overall_assessment(
    semester_reviews: list[SemesterReview],
    career_thread: list[CareerThreadEntry],
    activity_inventory: list[ActivityInventoryEntry],
) -> OverallAssessmentDraft:
    """종합 평가(SWOT) — 원본 데이터가 아니라 앞선 세 섹션의 "결과"만 입력으로
    받는다. 생기부를 아예 안 올린 사용자(전부 비어있음)라도 예외 없이 호출되므로,
    프롬프트가 빈 입력에도 정직하게 답하도록 규칙에 명시돼 있다."""
    user_content = json.dumps(
        {
            "semester_reviews": [s.model_dump() for s in semester_reviews],
            "career_thread": [t.model_dump() for t in career_thread],
            "activity_inventory": [e.model_dump(mode="json") for e in activity_inventory],
        },
        ensure_ascii=False,
    )
    return await call_structured(
        OVERALL_ASSESSMENT_SYSTEM_PROMPT, user_content, OverallAssessmentDraft
    )


async def run_diagnosis_pipeline(
    db: AsyncSession, user_id: uuid.UUID, interests: dict[str, Any]
) -> tuple[
    GradesTrend,
    list[SemesterReview],
    list[CareerThreadEntry],
    list[ActivityInventoryEntry],
    list[KnowledgeGraphLink],
    OverallAssessmentDraft,
]:
    user = await db.get(User, user_id)

    # AsyncSession은 동시 사용을 지원하지 않으므로, db를 직접 건드리는 조회는
    # 전부 먼저 순차적으로 끝낸다. LLM 호출만 아래에서 병렬로 돌린다.
    semester_groups = await get_semester_groups(db, user_id)
    career_material = await get_career_thread_material(db, user_id)
    activities_by_grade = await get_activities_by_grade(db, user_id)
    all_activities = [a for group in activities_by_grade.values() for a in group]
    fusion_candidates = generate_fusion_candidates(all_activities)
    grades_trend = await compute_grades_trend(db, user_id)

    # 학기별 평가·진로 유기적 평가·활동 인벤토리·지식 그래프는 서로 입력이
    # 겹치지 않는 독립 섹션이라 함께 병렬 실행한다(전부 LLM 호출만, db 접근 없음).
    (
        semester_reviews,
        career_thread,
        inventory_batches,
        knowledge_graph_links,
    ) = await asyncio.gather(
        asyncio.gather(*(_review_semester(g, interests) for g in semester_groups)),
        _write_career_thread(
            career_material,
            interests,
            user.current_grade if user else None,
            user.current_semester if user else None,
        ),
        asyncio.gather(
            *(
                _classify_activity_batch(grade, batch, interests)
                for grade, batch in activities_by_grade.items()
            )
        ),
        _write_knowledge_graph(fusion_candidates, interests),
    )
    semester_reviews = list(semester_reviews)
    activity_inventory = [entry for batch in inventory_batches for entry in batch]

    # 종합 평가는 위 세 섹션의 결과만 보고 판단한다 — 원본 데이터를 다시 훑지 않는다.
    overall = await _write_overall_assessment(semester_reviews, career_thread, activity_inventory)

    return (
        grades_trend,
        semester_reviews,
        career_thread,
        activity_inventory,
        knowledge_graph_links,
        overall,
    )
