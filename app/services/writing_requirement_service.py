"""전형별 원문 확인 상태를 보수적으로 갱신한다."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admission_catalog import AdmissionProgram, AdmissionTrack, University
from app.models.admission_writing_requirement_status import AdmissionWritingRequirementStatus
from app.models.admission_writing_source_document import AdmissionWritingSourceDocument
from app.services.writing_requirement_source import (
    WritingRequirementSource,
    WritingRequirementSourceError,
)


async def get_or_inspect_status(
    db: AsyncSession, *, track_id: object
) -> AdmissionWritingRequirementStatus | None:
    """원문을 한 번 검사해도 '없음'을 추정하지 않는다.

    단어 표식은 보조 근거일 뿐이며, 모집단위/전형 범위와 글자 수까지 확인된 뒤에만
    별도 수집 작업이 ``required`` 또는 ``not_required``로 승격할 수 있다.
    """
    existing = await db.scalar(
        select(AdmissionWritingRequirementStatus).where(
            AdmissionWritingRequirementStatus.track_id == track_id
        )
    )
    if existing:
        return existing

    row = await db.execute(
        select(AdmissionTrack, AdmissionProgram, University)
        .join(AdmissionProgram, AdmissionTrack.program_id == AdmissionProgram.id)
        .join(University, AdmissionProgram.university_id == University.id)
        .where(AdmissionTrack.id == track_id)
    )
    result = row.one_or_none()
    if not result:
        return None
    track, program, university = result
    status = AdmissionWritingRequirementStatus(
        track_id=track.id,
        requirement_status="unverified",
        source_admission_year=program.admission_year,
        source_status="plan",
        verification_note="수시모집요강 원문을 확인 중입니다.",
    )
    cached_document = await db.scalar(
        select(AdmissionWritingSourceDocument).where(
            AdmissionWritingSourceDocument.university_id == university.id,
            AdmissionWritingSourceDocument.source_admission_year == program.admission_year,
        )
    )
    if cached_document:
        status.source_admission_year = cached_document.source_admission_year
        status.source_url = cached_document.source_url
        status.source_status = "final"
        status.verified_at = cached_document.inspected_at
        if cached_document.inspection_status == "inspected":
            status.verification_note = (
                "대학 수시모집요강 원문은 사전 판독됐습니다. 전형별 적용 범위와 "
                "문항·글자 수를 추가 대조 중입니다."
            )
        else:
            status.verification_note = cached_document.inspection_note
        db.add(status)
        await db.commit()
        await db.refresh(status)
        return status
    try:
        async with WritingRequirementSource() as source:
            guide = await source.find_susi_guide(
                university_code=university.official_code,
                admission_year=program.admission_year,
            )
            if not guide:
                status.verification_note = (
                    f"{program.admission_year}학년도 수시모집요강 원문을 아직 찾지 못했습니다."
                )
            else:
                inspection = await source.inspect_guide(guide)
                status.source_admission_year = guide.admission_year
                status.source_url = guide.source_url
                status.source_status = "final"
                status.verified_at = inspection.inspected_at
                if inspection.marker_contexts:
                    status.verification_note = (
                        "모집요강에서 자기소개서 관련 표식을 찾았습니다. 전형별 적용 범위와 "
                        "문항·글자 수를 추가 대조 중입니다."
                    )
                else:
                    status.verification_note = (
                        "수시모집요강 원문은 읽었지만, 전형별 미요구 여부를 확정할 수 있는 "
                        "조항을 아직 대조하지 않았습니다."
                    )
    except (WritingRequirementSourceError, ValueError, OSError):
        status.verification_note = "모집요강 원문 자동 판독에 실패해 추가 확인이 필요합니다."
    db.add(status)
    await db.commit()
    await db.refresh(status)
    return status
