import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DiagnosisNotFoundError
from app.db.session import AsyncSessionLocal
from app.models.diagnosis import Diagnosis, DiagnosisStatus
from app.schemas.diagnosis import DiagnosisResult, PreQuestion, PreQuestionAnswer
from app.services.diagnosis import pipeline
from app.services.student_interest_service import get_current_interests, upsert_interest


async def has_completed_diagnosis_before(db: AsyncSession, user_id: uuid.UUID) -> bool:
    existing = await db.scalar(select(Diagnosis.id).where(Diagnosis.user_id == user_id).limit(1))
    return existing is not None


async def get_pre_questions(db: AsyncSession, user_id: uuid.UUID) -> list[PreQuestion]:
    """호환성을 위해 남긴 구 API. 진단 전 설문은 더 이상 생성하지 않는다.

    기록을 읽기도 전에 LLM이 성적 수준·학습 방식·동아리 같은 일반론을 질문하며
    학생을 멈춰 세우는 문제가 반복됐다. 진단은 보유한 사실 데이터만으로 먼저
    실행하고, 정말 필요한 확인은 기준일 문맥을 아는 상담 챗봇이 한 번에 하나씩
    대화 안에서 다룬다.
    """
    return []


async def submit_pre_question_answers(
    db: AsyncSession, user_id: uuid.UUID, answers: list[PreQuestionAnswer]
) -> None:
    """챗봇 대화와 동일하게 취급 — 저장시점 durability 필터를 거친 것만 반영."""
    extracted = await pipeline.extract_interests_from_answers(answers)
    for item in extracted.items:
        await upsert_interest(db, user_id, item.field_key, item.value)
    await db.commit()


async def create_diagnosis(db: AsyncSession, user_id: uuid.UUID) -> Diagnosis:
    diagnosis = Diagnosis(user_id=user_id, status=DiagnosisStatus.PROCESSING.value)
    db.add(diagnosis)
    await db.commit()
    await db.refresh(diagnosis)
    return diagnosis


async def run_diagnosis_job(diagnosis_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        diagnosis = await db.get(Diagnosis, diagnosis_id)
        if diagnosis is None:
            return

        try:
            interests = await get_current_interests(db, user_id)
            (
                grades_trend,
                semester_reviews,
                career_thread,
                activity_inventory,
                knowledge_graph_links,
                overall,
            ) = await pipeline.run_diagnosis_pipeline(db, user_id, interests)
            diagnosis.grades_trend = grades_trend.model_dump(mode="json")
            diagnosis.semester_reviews = [s.model_dump(mode="json") for s in semester_reviews]
            diagnosis.career_thread = [t.model_dump(mode="json") for t in career_thread]
            diagnosis.activity_inventory = [
                e.model_dump(mode="json") for e in activity_inventory
            ]
            diagnosis.knowledge_graph_links = [
                link.model_dump(mode="json") for link in knowledge_graph_links
            ]
            diagnosis.strengths = overall.strengths
            diagnosis.weaknesses = overall.weaknesses
            diagnosis.opportunities = overall.opportunities
            diagnosis.threats = overall.threats
            diagnosis.headline_comment = overall.headline_comment
            diagnosis.status = DiagnosisStatus.DONE.value
        except Exception as exc:
            diagnosis.status = DiagnosisStatus.FAILED.value
            diagnosis.failure_reason = f"{type(exc).__name__}: {exc}"

        await db.commit()


async def get_diagnosis(
    db: AsyncSession, user_id: uuid.UUID, diagnosis_id: uuid.UUID
) -> Diagnosis:
    diagnosis = await db.scalar(
        select(Diagnosis).where(Diagnosis.id == diagnosis_id, Diagnosis.user_id == user_id)
    )
    if diagnosis is None:
        raise DiagnosisNotFoundError("진단 결과를 찾을 수 없습니다")
    return diagnosis


async def get_latest_diagnosis(db: AsyncSession, user_id: uuid.UUID) -> Diagnosis:
    diagnosis = await db.scalar(
        select(Diagnosis)
        .where(Diagnosis.user_id == user_id)
        .order_by(Diagnosis.created_at.desc())
        .limit(1)
    )
    if diagnosis is None:
        raise DiagnosisNotFoundError("진단 결과를 찾을 수 없습니다")
    return diagnosis


def to_result(diagnosis: Diagnosis) -> DiagnosisResult:
    """상태와 무관하게 항상 반환 — processing/failed면 결과 필드가 비어있을 뿐."""
    return DiagnosisResult(
        diagnosis_id=diagnosis.id,
        status=diagnosis.status,
        grades_trend=diagnosis.grades_trend,
        semester_reviews=diagnosis.semester_reviews or [],
        career_thread=diagnosis.career_thread or [],
        activity_inventory=diagnosis.activity_inventory or [],
        knowledge_graph_links=diagnosis.knowledge_graph_links or [],
        strengths=diagnosis.strengths or [],
        weaknesses=diagnosis.weaknesses or [],
        opportunities=diagnosis.opportunities or [],
        threats=diagnosis.threats or [],
        headline_comment=diagnosis.headline_comment,
    )
