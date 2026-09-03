import asyncio
import json
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.activity_thread import ActivityThread
from app.models.user import User
from app.schemas.diagnosis import (
    ActivityInventoryDraft,
    ActivityInventoryEntry,
    CareerThread,
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
    CareerThreadMaterial,
    SemesterGroup,
    compute_grades_trend,
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

# 활동 설명은 원문이 길어 지식 그래프 입력에 그대로 실으면 165개 활동만으로도
# 컨텍스트가 커진다.
_KNOWLEDGE_GRAPH_DESCRIPTION_LIMIT = 200
# 이 개수를 넘으면 한 호출에 다 넣지 않고 인접 학년 쌍으로 나눠 부른다. 165개
# 규모는 실제 검증에서 문제없이 처리됐으므로, 그보다 확실히 낮게 여유를 두었다.
_KNOWLEDGE_GRAPH_BATCH_THRESHOLD = 120


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
    material: CareerThreadMaterial,
    interests: dict[str, Any],
    current_grade: int | None,
    current_semester: int | None,
) -> CareerThreadDraft:
    """진로 유기적 평가 — 활동/수상/봉사 전체를 입력받아 **주제별 갈래**로 엮는다.

    학기별 평가와 달리 전체 이력을 한 번에 봐야 '연결'을 판단할 수 있으므로 학기
    단위로 쪼개지 않는다. 시간순 평면 배열이 아니라 갈래로 묶는 이유는, 학생이 보통
    여러 주제를 동시에 굴리기 때문이다 — 한 줄에 섞어 놓으면 무엇이 무엇의 심화인지
    읽히지 않는다.
    """
    user_content = json.dumps(
        {
            "career_context": interests,
            "current_grade": current_grade,
            "current_semester": current_semester,
            **material.payload,
        },
        ensure_ascii=False,
    )
    return await call_structured(CAREER_THREAD_SYSTEM_PROMPT, user_content, CareerThreadDraft)


async def _persist_threads(
    db: AsyncSession,
    user_id: uuid.UUID,
    draft: CareerThreadDraft,
    index_of_activity: dict[int, Activity],
) -> list[CareerThread]:
    """갈래를 activity_threads에 남기고 활동에 thread_id를 붙인다.

    진단은 다시 돌릴 때마다 갈래를 새로 판단하므로, 이전 진단이 만든 갈래는 지우고
    새로 만든다. 학생이 직접 만든 갈래를 덮어쓰지 않도록 **진단이 만든 것만** 지운다
    (지금은 전부 진단이 만들지만, 수동 생성이 생겨도 이 경계가 유지되도록 표시를
    남겨 둔다).
    """
    previous = list(
        await db.scalars(select(ActivityThread).where(ActivityThread.user_id == user_id))
    )
    for thread in previous:
        # 활동은 남기고 연결만 끊는다 — 갈래는 해석이고 활동은 사실이다.
        await db.execute(
            update(Activity)
            .where(Activity.thread_id == thread.id)
            .values(thread_id=None)
        )
        await db.delete(thread)

    result: list[CareerThread] = []
    for drafted in draft.career_thread:
        thread = ActivityThread(
            user_id=user_id, title=drafted.title, description=drafted.summary
        )
        db.add(thread)
        await db.flush()

        for index in drafted.activity_indexes:
            activity = index_of_activity.get(index)
            # LLM이 지어낸 index는 조용히 버린다 — 정수라 오타가 나도 범위 검사만으로
            # 걸러지고, 응답 전체가 무효가 되지 않는다.
            if activity is not None:
                activity.thread_id = thread.id

        result.append(
            CareerThread(
                title=drafted.title,
                summary=drafted.summary,
                # 프롬프트가 학년-학기 순을 요구하지만 실제 응답에서 뒤섞여 나오는 것을
                # 관측했다. 갈래는 "흐름"으로 읽히는 것이 전부라 순서가 어긋나면 의미가
                # 무너지므로 코드에서 보증한다. 학기가 없는 노드(자율활동 등)는 그 학년
                # 안에서 맨 앞에 둔다.
                entries=sorted(
                    drafted.entries, key=lambda e: (e.grade, e.semester if e.semester else 0)
                ),
            )
        )

    return result


async def _classify_activity_batch(
    grade: int, activities: list[Activity], interests: dict[str, Any]
) -> list[ActivityInventoryEntry]:
    """활동 인벤토리 — 학년 단위 배치 호출. 진로 유기적 평가와 달리 필터링하지
    않고 입력된 활동 전량에 분류를 매긴다.

    LLM에게 activity_id(UUID)를 그대로 베끼게 하면 한 글자만 틀려도 그 배치
    전체의 파싱이 깨진다(실제로 관측됨). 대신 이 호출 안에서만 유효한 정수
    index를 주고, 응답의 index를 실제 activity_id로 역참조한다."""
    index_of_activity = dict(enumerate(activities, start=1))
    payload = [
        {
            "index": index,
            "grade": a.grade,
            "semester": a.semester,
            "activity_category": a.activity_category,
            "subject": a.subject,
            "activity_name": a.activity_name,
            "description": a.description,
            "keywords": a.keywords,
        }
        for index, a in index_of_activity.items()
    ]
    user_content = json.dumps(
        {"grade": grade, "career_context": interests, "activities": payload}, ensure_ascii=False
    )
    draft = await call_structured(
        ACTIVITY_INVENTORY_SYSTEM_PROMPT, user_content, ActivityInventoryDraft
    )

    entries: list[ActivityInventoryEntry] = []
    for draft_entry in draft.entries:
        activity = index_of_activity.get(draft_entry.index)
        if activity is None:
            continue  # LLM이 지어내거나 범위를 벗어난 index — 버린다.
        entries.append(
            ActivityInventoryEntry(
                activity_id=activity.id,
                grade=activity.grade,
                semester=activity.semester,
                competency=draft_entry.competency,
                depth_level=draft_entry.depth_level,
                headline=draft_entry.headline,
            )
        )
    return entries


async def _write_knowledge_graph_batch(
    activities: list[Activity], interests: dict[str, Any]
) -> list[KnowledgeGraphLink]:
    """지식 그래프 한 배치 호출. activity_id 대신 index를 쓰는 이유는
    _classify_activity_batch와 같다."""
    if not activities:
        return []

    index_of_activity = dict(enumerate(activities, start=1))
    index_by_id = {a.id: index for index, a in index_of_activity.items()}
    payload = [
        {
            "index": index,
            "grade": a.grade,
            "semester": a.semester,
            "subject": a.subject,
            "activity_name": a.activity_name,
            "description": (a.description or "")[:_KNOWLEDGE_GRAPH_DESCRIPTION_LIMIT],
            "keywords": a.keywords,
            # 이미 계보로 이어진 부모 — 이 링크는 진로 유기적 평가가 다루므로
            # 지식 그래프에서 중복해서 만들지 않도록 알려준다.
            "parent_activity_index": (
                index_by_id.get(a.parent_activity_id) if a.parent_activity_id else None
            ),
        }
        for index, a in index_of_activity.items()
    ]
    # 활동마다 parent_activity_index를 흩어 놓기만 하면 LLM이 규칙을 흘려보내고
    # 계보 쌍만 잔뜩 돌려주는 것이 실제로 관측됐다. 제외 대상을 한 곳에 모아
    # 명시적으로 건네 애초에 후보에서 빠지게 한다(코드 필터는 그대로 둔다 —
    # 프롬프트는 부탁이고 필터가 보증이다).
    already_linked = [
        [index_by_id[a.parent_activity_id], index]
        for index, a in index_of_activity.items()
        if a.parent_activity_id is not None and a.parent_activity_id in index_by_id
    ]
    user_content = json.dumps(
        {
            "career_context": interests,
            "activities": payload,
            "already_linked_pairs": already_linked,
        },
        ensure_ascii=False,
    )
    draft = await call_structured(KNOWLEDGE_GRAPH_SYSTEM_PROMPT, user_content, KnowledgeGraphDraft)

    # 이미 parent_activity_id로 이어진 쌍은 진로 유기적 평가·계보 화면이 이미
    # 다루므로 그래프에 다시 올리지 않는다. 프롬프트에도 같은 규칙을 적어 두었지만
    # LLM이 실제로 이 지시를 무시하고 계보 쌍만 잔뜩 돌려주는 것이 관측돼(그러면
    # 그래프가 계보의 중복이 되어 아무 정보도 더하지 못한다), 지어낸 index를
    # 버리는 것과 같은 방식으로 코드에서 확정적으로 걸러낸다.
    lineage_pairs = {
        frozenset({a.id, a.parent_activity_id})
        for a in activities
        if a.parent_activity_id is not None
    }

    links: list[KnowledgeGraphLink] = []
    seen: set[frozenset[uuid.UUID]] = set()
    for draft_link in draft.links:
        from_activity = index_of_activity.get(draft_link.from_index)
        to_activity = index_of_activity.get(draft_link.to_index)
        if from_activity is None or to_activity is None:
            continue
        if from_activity.id == to_activity.id:
            continue
        pair = frozenset({from_activity.id, to_activity.id})
        if pair in lineage_pairs or pair in seen:
            continue
        seen.add(pair)
        links.append(
            KnowledgeGraphLink(
                from_activity_id=from_activity.id,
                to_activity_id=to_activity.id,
                link_type=draft_link.link_type,
                relation_label=draft_link.relation_label,
            )
        )
    return links


async def _write_knowledge_graph(
    activities_by_grade: dict[int, list[Activity]], interests: dict[str, Any]
) -> list[KnowledgeGraphLink]:
    """지식 그래프 — 과목명이 같은지·키워드가 겹치는지로 후보를 미리 좁히지
    않는다. 한국 고교 교육과정은 같은 과목이 여러 학기에 반복되는 경우가 드물어
    (화학Ⅰ→화학Ⅱ처럼 과목명 자체가 바뀌며 심화된다), 문자열 매칭으로는 실제
    심화 관계를 거의 못 찾는다 — 대신 활동 전체를 LLM에 통째로 주고 내용을 읽고
    직접 판단하게 한다(career_thread와 같은 패턴).

    다만 활동이 아주 많은 사용자는 한 호출에 다 넣으면 출력이 잘리거나 품질이
    떨어질 수 있다(activity_inventory에서 실제로 UUID가 깨지는 사고를 겪었다 —
    지금은 index로 막았지만 '한 호출에 너무 많이 담는' 근본 위험은 남아 있다).
    임계값을 넘으면 인접한 두 학년씩 묶어 나눠 호출한다 — 실제 심화 관계는
    거의 항상 인접 학년 사이(1→2, 2→3)에서 일어나므로 이 창으로도 대부분
    잡히고, 겹치는 학년에서 중복으로 찾은 링크는 병합 시 걸러낸다."""
    all_activities = [a for batch in activities_by_grade.values() for a in batch]
    if len(all_activities) <= _KNOWLEDGE_GRAPH_BATCH_THRESHOLD:
        return await _write_knowledge_graph_batch(all_activities, interests)

    grades = sorted(activities_by_grade)
    windows = (
        [[g, grades[i + 1]] for i, g in enumerate(grades[:-1])] if len(grades) > 1 else [grades]
    )
    batches = await asyncio.gather(
        *(
            _write_knowledge_graph_batch(
                [a for g in window for a in activities_by_grade[g]], interests
            )
            for window in windows
        )
    )

    seen: set[frozenset[uuid.UUID]] = set()
    merged: list[KnowledgeGraphLink] = []
    for batch in batches:
        for link in batch:
            pair = frozenset({link.from_activity_id, link.to_activity_id})
            if pair in seen:
                continue
            seen.add(pair)
            merged.append(link)
    return merged


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
    list[CareerThread],
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
    grades_trend = await compute_grades_trend(db, user_id)

    # 학기별 평가·진로 유기적 평가·활동 인벤토리·지식 그래프는 서로 입력이
    # 겹치지 않는 독립 섹션이라 함께 병렬 실행한다(전부 LLM 호출만, db 접근 없음).
    (
        semester_reviews,
        career_thread_draft,
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
        _write_knowledge_graph(activities_by_grade, interests),
    )
    semester_reviews = list(semester_reviews)
    activity_inventory = [entry for batch in inventory_batches for entry in batch]

    # 갈래를 실제 데이터로 남긴다(activity_threads + activities.thread_id). 진단
    # 출력만이 아니라 지속되는 구조라, 이후 지식 그래프·챗봇이 "같은 갈래인가"를
    # 물을 수 있다. LLM 호출이 아니라 DB 쓰기라 병렬 구간 밖에서 순차로 처리한다.
    career_thread = await _persist_threads(
        db, user_id, career_thread_draft, career_material.index_of_activity
    )

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
