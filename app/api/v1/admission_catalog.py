"""대학 → 모집단위 → 전형 순서로 고르는 지원처 카탈로그 API."""

import re
import uuid
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.admission_catalog import AdmissionProgram, AdmissionTrack, University
from app.models.admission_program_reference import (
    AdmissionProgramOutcome,
    AdmissionProgramReference,
)
from app.models.admission_university_guide import AdmissionUniversityGuide
from app.models.admission_university_snapshot import AdmissionUniversitySnapshot
from app.models.admission_writing_requirement import AdmissionWritingRequirement
from app.models.user import User
from app.schemas.admission_catalog import (
    AdmissionProgramOutcomeRead,
    AdmissionProgramPastResultsRead,
    AdmissionProgramProfileRead,
    AdmissionProgramProfileSectionRead,
    AdmissionProgramRead,
    AdmissionTrackDetailRead,
    AdmissionTrackRead,
    AdmissionTrackReferenceRead,
    AdmissionTrackResearchRead,
    AdmissionUniversityGuideRead,
    AdmissionUniversityGuideSectionRead,
    UniversityAdmissionStatisticsRead,
    UniversitySearchRead,
)
from app.schemas.admission_writing_requirement import (
    AdmissionWritingRequirementRead,
    AdmissionWritingRequirementsResponse,
    AdmissionWritingRequirementStatusRead,
)
from app.services import admission_catalog_service
from app.services.adiga_catalog_source import AdigaSourceError
from app.services.admission_research_service import get_admission_research
from app.services.snu_admission_service import get_snu_2027_susi_detail
from app.services.writing_requirement_service import get_or_inspect_status

router = APIRouter(prefix="/admission-catalog", tags=["admission-catalog"])


@router.get("/universities", response_model=list[UniversitySearchRead])
async def search_universities(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str = Query(default="", max_length=60),
    limit: int = Query(default=12, ge=1, le=30),
) -> list[UniversitySearchRead]:
    del user
    rows = await admission_catalog_service.search_universities(db, q, limit)
    return [UniversitySearchRead.model_validate(row) for row in rows]


@router.get(
    "/universities/{university_id}/statistics",
    response_model=UniversityAdmissionStatisticsRead,
)
async def university_statistics(
    university_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    source_admission_year: int = Query(default=2026, ge=2024, le=2035),
) -> UniversityAdmissionStatisticsRead:
    """대입정보포털이 공개한 대학 전체 통계를 출처/기준연도와 함께 반환한다."""
    del user
    row = await db.scalar(
        select(AdmissionUniversitySnapshot).where(
            AdmissionUniversitySnapshot.university_id == university_id,
            AdmissionUniversitySnapshot.source_admission_year == source_admission_year,
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="아직 수집하지 않은 대학 통계입니다.",
        )
    payload = row.payload
    return UniversityAdmissionStatisticsRead(
        source_admission_year=row.source_admission_year,
        source_url=row.source_url,
        verified_at=row.verified_at,
        recruitment_and_applicants=payload.get("recruitment_and_applicants", []),
        selection_distribution=payload.get("selection_distribution", []),
        employment_rate=payload.get("employment_rate", []),
        competition_rate=payload.get("competition_rate", []),
    )


@router.get(
    "/universities/{university_id}/admission-guide",
    response_model=AdmissionUniversityGuideRead,
)
async def university_admission_guide(
    university_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    source_admission_year: int = Query(default=2027, ge=2024, le=2035),
) -> AdmissionUniversityGuideRead:
    """요청 학년도가 없으면 그 이전의 가장 최근 공개 대학 가이드를 반환한다."""
    del user
    rows = list(
        await db.scalars(
        select(AdmissionUniversityGuide)
        .where(
            AdmissionUniversityGuide.university_id == university_id,
            AdmissionUniversityGuide.source_admission_year <= source_admission_year,
        )
        .order_by(AdmissionUniversityGuide.source_admission_year.desc())
        )
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="아직 수집하지 않은 대학 입시가이드입니다.",
        )
    # 최신 원천이 일부 탭만 제공하는 경우에는, 없는 탭만 바로 이전의 공개본으로
    # 보완한다. 이렇게 해야 새 수시·정시 정보는 유지하면서도 '입시가이드' 자리를
    # 확인 필요로 비워 두지 않는다. 각 탭의 실제 기준 연도는 응답에도 남긴다.
    section_by_title: dict[str, AdmissionUniversityGuideSectionRead] = {}
    for row in rows:
        for section in row.sections:
            title = section.get("title") if isinstance(section, dict) else None
            if not isinstance(title, str) or title in section_by_title:
                continue
            section_by_title[title] = AdmissionUniversityGuideSectionRead(
                **section,
                source_admission_year=row.source_admission_year,
                source_url=row.source_url,
            )
    section_order = {"수시 대입특징": 0, "정시 대입특징": 1, "입시가이드": 2}
    sections = sorted(
        section_by_title.values(),
        key=lambda section: section_order.get(section.title, 99),
    )
    latest = rows[0]
    return AdmissionUniversityGuideRead(
        source_admission_year=latest.source_admission_year,
        source_url=latest.source_url,
        verified_at=latest.verified_at,
        sections=sections,
    )


@router.get("/universities/{university_id}/programs", response_model=list[AdmissionProgramRead])
async def list_programs(
    university_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    admission_year: int = Query(ge=2026, le=2035),
    q: str = Query(default="", max_length=60),
    limit: int = Query(default=40, ge=1, le=100),
) -> list[AdmissionProgramRead]:
    del user
    try:
        rows = await admission_catalog_service.list_programs(
            db, university_id, admission_year, q, limit
        )
    except (AdigaSourceError, httpx.HTTPError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="공식 모집 정보에 일시적으로 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
        ) from error
    return [AdmissionProgramRead.model_validate(row) for row in rows]


@router.get("/programs/{program_id}/tracks", response_model=list[AdmissionTrackRead])
async def list_tracks(
    program_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AdmissionTrackRead]:
    del user
    try:
        rows = await admission_catalog_service.list_tracks(db, program_id)
    except (AdigaSourceError, httpx.HTTPError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="공식 모집 정보에 일시적으로 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
        ) from error
    return [AdmissionTrackRead.model_validate(row) for row in rows]


@router.get("/tracks/{track_id}/reference", response_model=AdmissionTrackReferenceRead)
async def track_reference(
    track_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    del user
    row = await db.execute(
        select(AdmissionTrack, AdmissionProgram, University)
        .join(AdmissionProgram, AdmissionTrack.program_id == AdmissionProgram.id)
        .join(University, AdmissionProgram.university_id == University.id)
        .where(AdmissionTrack.id == track_id)
    )
    result = row.one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="전형을 찾지 못했습니다.")
    track, program, university = result
    async with admission_catalog_service.AdigaCatalogSource() as source:
        source_url = ""
        parsed = None
        source_year = program.admission_year - 1
        # 올해 자료가 아직 없을 때 가장 최근 공개 자료부터 순서대로 쓴다. 대학이
        # 특정 해에 자료를 올리지 않았더라도, 더 오래된 자료를 먼저 보여주지 않는다.
        for candidate_year in range(program.admission_year - 1, 2023, -1):
            source_url, parsed = await source.fetch_track_reference(
                university_code=university.official_code,
                admission_year=candidate_year,
                track_name=track.name,
            )
            source_year = candidate_year
            if parsed:
                break
    if not parsed:
        return AdmissionTrackReferenceRead(
            source_admission_year=source_year,
            source_url=source_url,
            has_document_review=None,
            has_interview=None,
            has_minimum_requirement=None,
            summary=(
                "가장 최근 공개 자료에서도 이 전형군의 세부 기준을 읽지 못했습니다. "
                "공식 원문을 확인해 주세요."
            ),
        )
    document, interview, minimum, summary = parsed
    return AdmissionTrackReferenceRead(
        source_admission_year=source_year,
        source_url=source_url,
        has_document_review=document,
        has_interview=interview,
        has_minimum_requirement=minimum,
        summary=summary,
    )


@router.get("/tracks/{track_id}/detail", response_model=AdmissionTrackDetailRead)
async def track_detail(
    track_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdmissionTrackDetailRead:
    """대학별로 수집·검증된 전형 상세. 현재 서울대 2027 수시만 제공한다."""
    del user
    row = await db.execute(
        select(AdmissionTrack, AdmissionProgram, University)
        .join(AdmissionProgram, AdmissionTrack.program_id == AdmissionProgram.id)
        .join(University, AdmissionProgram.university_id == University.id)
        .where(AdmissionTrack.id == track_id)
    )
    result = row.one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="전형을 찾지 못했습니다.")
    track, program, university = result
    detail = (
        get_snu_2027_susi_detail(track_name=track.name, program_name=program.name)
        if university.name == "서울대학교" and program.admission_year == 2027
        else None
    )
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail="아직 상세 수집을 지원하지 않는 대학·전형입니다.",
        )
    return AdmissionTrackDetailRead(**detail.__dict__)


@router.get("/tracks/{track_id}/research", response_model=AdmissionTrackResearchRead)
async def track_research(
    track_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdmissionTrackResearchRead:
    """대학·단과대학·학과·전형 단위의 수집 정보를 공통 카드 형식으로 제공한다."""
    del user
    row = await db.execute(
        select(AdmissionTrack, AdmissionProgram, University)
        .join(AdmissionProgram, AdmissionTrack.program_id == AdmissionProgram.id)
        .join(University, AdmissionProgram.university_id == University.id)
        .where(AdmissionTrack.id == track_id)
    )
    result = row.one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="전형을 찾지 못했습니다.")
    track, program, university = result
    cards = get_admission_research(
        university_name=university.name,
        program_name=program.name,
        track_name=track.name,
    )
    return AdmissionTrackResearchRead(
        university_name=university.name,
        program_name=program.name,
        track_name=track.name,
        cards=[card.__dict__ for card in cards],
    )


def _normalized_program_name(value: str) -> str:
    """연도별 주·야간 표기 등 비교에 불필요한 표기를 제거한다.

    이름이 완전히 다르면 연결하지 않는다. 유사도 추정으로 다른 모집단위의 입결을
    보여주는 것보다, 정보가 없다고 알리는 편이 안전하다.
    """
    return re.sub(r"[^0-9a-z가-힣]", "", re.sub(r"\([^)]*\)", "", value.lower()))


@router.get(
    "/tracks/{track_id}/past-results",
    response_model=AdmissionProgramPastResultsRead,
)
async def track_past_results(
    track_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdmissionProgramPastResultsRead:
    """현재 모집단위에 이름이 정확히 대응하는 가장 최신 과거 공개 입시결과."""
    del user
    selected = await db.execute(
        select(AdmissionTrack, AdmissionProgram, University)
        .join(AdmissionProgram, AdmissionTrack.program_id == AdmissionProgram.id)
        .join(University, AdmissionProgram.university_id == University.id)
        .where(AdmissionTrack.id == track_id)
    )
    result = selected.one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="전형을 찾지 못했습니다.")
    _, program, university = result
    candidates = list(
        await db.scalars(
            select(AdmissionProgramReference)
            .where(AdmissionProgramReference.university_id == university.id)
            .order_by(AdmissionProgramReference.source_admission_year.desc())
        )
    )
    target_name = _normalized_program_name(program.name)
    reference = next(
        (
            candidate
            for candidate in candidates
            if _normalized_program_name(candidate.name) == target_name
        ),
        None,
    )
    if reference is None:
        raise HTTPException(
            status_code=404,
            detail="이 모집단위와 이름이 정확히 대응하는 과거 공개 입시결과가 없습니다.",
        )
    outcomes = list(
        await db.scalars(
            select(AdmissionProgramOutcome)
            .where(AdmissionProgramOutcome.program_reference_id == reference.id)
            .order_by(
                AdmissionProgramOutcome.recruitment_period,
                AdmissionProgramOutcome.selection_type,
                AdmissionProgramOutcome.selection_name,
            )
        )
    )
    if not outcomes:
        raise HTTPException(
            status_code=404,
            detail="이 학과는 해당 연도 공개 입시결과를 제공하지 않았습니다.",
        )
    return AdmissionProgramPastResultsRead(
        source_admission_year=reference.source_admission_year,
        reference_program_name=reference.name,
        source_url=reference.source_url,
        outcomes=[AdmissionProgramOutcomeRead.model_validate(row) for row in outcomes],
    )


@router.get(
    "/tracks/{track_id}/program-profile",
    response_model=AdmissionProgramProfileRead,
)
async def track_program_profile(
    track_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdmissionProgramProfileRead:
    """현재 모집단위와 이름이 정확히 대응하는 과거 학과 소개를 반환한다."""
    del user
    selected = await db.execute(
        select(AdmissionProgram, University)
        .join(University, AdmissionProgram.university_id == University.id)
        .join(AdmissionTrack, AdmissionTrack.program_id == AdmissionProgram.id)
        .where(AdmissionTrack.id == track_id)
    )
    result = selected.one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="전형을 찾지 못했습니다.")
    program, university = result
    references = list(
        await db.scalars(
            select(AdmissionProgramReference)
            .where(AdmissionProgramReference.university_id == university.id)
            .order_by(AdmissionProgramReference.source_admission_year.desc())
        )
    )
    target_name = _normalized_program_name(program.name)
    reference = next(
        (
            candidate
            for candidate in references
            if _normalized_program_name(candidate.name) == target_name
        ),
        None,
    )
    if reference is None or not reference.detail_sections:
        raise HTTPException(
            status_code=404,
            detail="이 모집단위와 이름이 정확히 대응하는 공개 학과 소개가 없습니다.",
        )
    return AdmissionProgramProfileRead(
        source_admission_year=reference.source_admission_year,
        reference_program_name=reference.name,
        academic_field=reference.academic_field,
        recruitment_count=reference.recruitment_count,
        early_competition_rate=reference.early_competition_rate,
        regular_competition_rate=reference.regular_competition_rate,
        source_url=reference.source_url,
        sections=[
            AdmissionProgramProfileSectionRead.model_validate(section)
            for section in reference.detail_sections
        ],
    )


@router.get(
    "/tracks/{track_id}/writing-requirements",
    response_model=AdmissionWritingRequirementsResponse,
)
async def list_writing_requirements(
    track_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdmissionWritingRequirementsResponse:
    """공식 자기소개·에세이 문항이 확인된 경우에만 반환한다.

    빈 배열은 제출 서류가 없다는 뜻이 아니라, 아직 최종 모집요강에서 확인되지
    않았다는 뜻이다.
    """
    del user
    status_row = await get_or_inspect_status(db, track_id=track_id)
    if status_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="전형을 찾지 못했습니다.")
    rows = list(
        await db.scalars(
            select(AdmissionWritingRequirement)
            .where(AdmissionWritingRequirement.track_id == track_id)
            .order_by(AdmissionWritingRequirement.prompt_order)
        )
    )
    return AdmissionWritingRequirementsResponse(
        status=AdmissionWritingRequirementStatusRead.model_validate(status_row),
        requirements=[AdmissionWritingRequirementRead.model_validate(row) for row in rows],
    )
