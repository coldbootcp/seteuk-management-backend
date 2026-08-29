import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DiagnosisNotFoundError
from app.db.session import AsyncSessionLocal
from app.models.diagnosis import Diagnosis, DiagnosisStatus
from app.schemas.diagnosis import DiagnosisResult, PreQuestion, PreQuestionAnswer
from app.services.diagnosis import pipeline
from app.services.diagnosis.data import get_domain_rows
from app.services.student_interest_service import get_current_interests, upsert_interest


async def has_completed_diagnosis_before(db: AsyncSession, user_id: uuid.UUID) -> bool:
    existing = await db.scalar(select(Diagnosis.id).where(Diagnosis.user_id == user_id).limit(1))
    return existing is not None


async def get_pre_questions(db: AsyncSession, user_id: uuid.UUID) -> list[PreQuestion]:
    """최초 진단 전에만 사전질문을 낸다 — 재진단부턴 항상 빈 배열."""
    if await has_completed_diagnosis_before(db, user_id):
        return []

    interests = await get_current_interests(db, user_id)
    seteuk_summary = await get_domain_rows(db, user_id)
    return await pipeline.generate_pre_questions(interests, seteuk_summary)


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
            semester_summaries, domain_feedback, synthesis = await pipeline.run_diagnosis_pipeline(
                db, user_id, interests
            )
            diagnosis.semester_summaries = [s.model_dump(mode="json") for s in semester_summaries]
            diagnosis.domain_feedback = [d.model_dump(mode="json") for d in domain_feedback]
            diagnosis.career_thread = [t.model_dump(mode="json") for t in synthesis.career_thread]
            diagnosis.overall_summary = synthesis.overall_summary
            diagnosis.strengths = synthesis.strengths
            diagnosis.weaknesses = synthesis.weaknesses
            diagnosis.career_gap_analysis = synthesis.career_gap_analysis
            diagnosis.keyword_map = synthesis.keyword_map
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
        semester_summaries=diagnosis.semester_summaries or [],
        domain_feedback=diagnosis.domain_feedback or [],
        career_thread=diagnosis.career_thread or [],
        overall_summary=diagnosis.overall_summary,
        strengths=diagnosis.strengths or [],
        weaknesses=diagnosis.weaknesses or [],
        career_gap_analysis=diagnosis.career_gap_analysis,
        keyword_map=diagnosis.keyword_map or [],
    )
