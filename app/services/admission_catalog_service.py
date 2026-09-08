"""공식 모집 정보 카탈로그 조회. 학생별 데이터를 섞지 않는다."""

import re
import uuid

from sqlalchemy import Select, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admission_catalog import AdmissionProgram, AdmissionTrack, University
from app.models.admission_program_reference import (
    AdmissionProgramOutcome,
    AdmissionProgramReference,
)
from app.models.admission_university_guide import AdmissionUniversityGuide
from app.models.admission_university_snapshot import AdmissionUniversitySnapshot
from app.services.adiga_catalog_source import (
    ADMISSION_VIEW_URL,
    BASE_URL,
    UNIVERSITY_VIEW_URL,
    AdigaCatalogSource,
)


def _keyword_filter(statement: Select, column: object, query: str) -> Select:
    keyword = query.strip()
    return statement.where(column.ilike(f"%{keyword}%")) if keyword else statement


async def search_universities(db: AsyncSession, query: str, limit: int) -> list[University]:
    statement = (
        select(University)
        .where(University.is_active.is_(True))
        .order_by(University.name)
        .limit(limit)
    )
    statement = _keyword_filter(statement, University.name, query)
    return list(await db.scalars(statement))


async def list_programs(
    db: AsyncSession, university_id: uuid.UUID, admission_year: int, query: str, limit: int
) -> list[AdmissionProgram]:
    existing = await db.scalar(
        select(AdmissionProgram.id).where(
            AdmissionProgram.university_id == university_id,
            AdmissionProgram.admission_year == admission_year,
        ).limit(1)
    )
    if existing is None:
        university = await db.scalar(select(University).where(University.id == university_id))
        if university is not None:
            await sync_programs_for_university(db, university, admission_year)
            await db.commit()
    statement = (
        select(AdmissionProgram)
        .where(
            AdmissionProgram.university_id == university_id,
            AdmissionProgram.admission_year == admission_year,
            AdmissionProgram.is_recruiting.is_(True),
        )
        .order_by(AdmissionProgram.name)
        .limit(limit)
    )
    statement = _keyword_filter(statement, AdmissionProgram.name, query)
    return list(await db.scalars(statement))


async def list_tracks(db: AsyncSession, program_id: uuid.UUID) -> list[AdmissionTrack]:
    existing = await db.scalar(
        select(AdmissionTrack.id).where(AdmissionTrack.program_id == program_id).limit(1)
    )
    if existing is None:
        program = await db.scalar(select(AdmissionProgram).where(AdmissionProgram.id == program_id))
        if program is not None:
            await sync_tracks_for_program(db, program)
            await db.commit()
    statement = (
        select(AdmissionTrack)
        .where(AdmissionTrack.program_id == program_id)
        .order_by(AdmissionTrack.name)
    )
    return list(await db.scalars(statement))


async def sync_general_universities(db: AsyncSession) -> int:
    """일반대학 목록만 새로 읽어 upsert한다. 전문대학 경로는 절대 사용하지 않는다."""
    async with AdigaCatalogSource() as source:
        source_rows = await source.fetch_general_universities()
        verified_at = source.verified_at

    # 포털은 동일한 표시명에 다른 내부 코드를 붙여 중복 반환하는 경우가 있다.
    # DB의 식별 제약도 표시명 기준이므로, 먼저 원천 결과를 같은 기준으로 합친다.
    source_by_name = {row.name: row for row in source_rows}
    existing = {
        row.official_code: row for row in await db.scalars(select(University))
    }
    for row in source_by_name.values():
        university = existing.get(row.official_code)
        if university is None:
            db.add(
                University(
                    official_code=row.official_code,
                    name=row.name,
                    campus_name=row.campus_name,
                    source_url=UNIVERSITY_VIEW_URL,
                    verified_at=verified_at,
                )
            )
            continue
        university.name = row.name
        university.campus_name = row.campus_name
        university.source_url = UNIVERSITY_VIEW_URL
        university.is_active = True
        university.verified_at = verified_at
    await db.flush()
    return len(source_by_name)


async def sync_programs_for_university(
    db: AsyncSession, university: University, admission_year: int
) -> int:
    """한 대학의 해당 연도 모집단위를 공식 포털에서 가져와 갱신한다.

    대학 하나를 선택했을 때만 호출할 수 있게 작게 나눴다. 전체 4년제 목록을 매번
    다시 긁지 않으며, 원천 오류가 나도 기존 데이터는 남는다.
    """
    async with AdigaCatalogSource() as source:
        source_rows = await source.fetch_programs(
            university_code=university.official_code,
            university_name=university.name,
            admission_year=admission_year,
        )
        # 포털은 '건국대학교(글로컬)' 같은 공식 표시명을 검색어로 받으면 0건을
        # 돌려주면서, 괄호 앞의 학교명 검색에는 같은 내부 코드의 결과를 반환한다.
        # 코드로 한 번 더 걸러 내므로 다른 캠퍼스의 모집단위가 섞일 위험은 없다.
        if not source_rows:
            base_name = re.sub(r"\([^)]*\)", "", university.name).strip()
            if base_name and base_name != university.name:
                source_rows = await source.fetch_programs(
                    university_code=university.official_code,
                    university_name=base_name,
                    admission_year=admission_year,
                )
        verified_at = source.verified_at

    existing = {
        row.source_program_code: row
        for row in await db.scalars(
            select(AdmissionProgram).where(
                AdmissionProgram.university_id == university.id,
                AdmissionProgram.admission_year == admission_year,
            )
        )
        if row.source_program_code
    }
    for row in source_rows:
        program = existing.get(row.program_code)
        if program is None:
            db.add(
                AdmissionProgram(
                    university_id=university.id,
                    admission_year=admission_year,
                    source_program_code=row.program_code,
                    name=row.name,
                    source_url=ADMISSION_VIEW_URL,
                    source_status="plan",
                    verified_at=verified_at,
                )
            )
            continue
        program.name = row.name
        program.source_url = ADMISSION_VIEW_URL
        program.source_status = "plan"
        program.is_recruiting = True
        program.verified_at = verified_at
    await db.flush()
    return len(source_rows)


async def sync_tracks_for_program(db: AsyncSession, program: AdmissionProgram) -> int:
    """모집단위를 고른 뒤에만 그 전형을 수집한다."""
    if not program.source_program_code:
        return 0
    university = await db.scalar(select(University).where(University.id == program.university_id))
    if university is None:
        return 0

    async with AdigaCatalogSource() as source:
        source_rows = await source.fetch_tracks(
            university_code=university.official_code,
            program_code=program.source_program_code,
            admission_year=program.admission_year,
        )
        verified_at = source.verified_at

    # 같은 표시명에 서로 다른 포털 내부 코드가 붙은 중복 행을 제거한다.
    # 테이블의 고유 제약도 표시명 기준이므로 그대로 넣으면 동기화가 실패한다.
    source_by_name = {row.name: row for row in source_rows}
    existing = {
        row.name: row
        for row in await db.scalars(
            select(AdmissionTrack).where(AdmissionTrack.program_id == program.id)
        )
    }
    for row in source_by_name.values():
        track = existing.get(row.name)
        if track is None:
            db.add(
                AdmissionTrack(
                    program_id=program.id,
                    name=row.name,
                    admission_type=row.admission_type,
                    recruitment_period=row.recruitment_period,
                    source_url=ADMISSION_VIEW_URL,
                    source_status="plan",
                    verified_at=verified_at,
                )
            )
            continue
        track.admission_type = row.admission_type
        track.recruitment_period = row.recruitment_period
        track.source_url = ADMISSION_VIEW_URL
        track.source_status = "plan"
        track.verified_at = verified_at
    await db.flush()
    return len(source_by_name)


async def sync_university_statistics(
    db: AsyncSession, university: University, admission_year: int
) -> AdmissionUniversitySnapshot:
    """대입정보포털의 대학 전체 통계 차트를 연도별 스냅샷으로 갱신한다."""
    async with AdigaCatalogSource() as source:
        source_row = await source.fetch_university_statistics(
            university_code=university.official_code,
            admission_year=admission_year,
        )
        verified_at = source.verified_at

    row = await db.scalar(
        select(AdmissionUniversitySnapshot).where(
            AdmissionUniversitySnapshot.university_id == university.id,
            AdmissionUniversitySnapshot.source_admission_year == admission_year,
        )
    )
    if row is None:
        row = AdmissionUniversitySnapshot(
            university_id=university.id,
            source_admission_year=admission_year,
            source_url=source_row.source_url,
            payload=source_row.payload,
            verified_at=verified_at,
        )
        db.add(row)
    else:
        row.source_url = source_row.source_url
        row.payload = source_row.payload
        row.verified_at = verified_at
    await db.flush()
    return row


async def sync_university_admission_guide(
    db: AsyncSession, university: University, source_admission_year: int
) -> AdmissionUniversityGuide:
    """대학 공통 수시·정시 대입특징과 입시가이드를 해당 학년도로 갱신한다.

    원천 연결 또는 파싱에 실패하면 이 함수는 flush 이전에 예외를 내므로 기존에
    저장한 가장 최근 가이드가 사라지지 않는다.
    """
    async with AdigaCatalogSource() as source:
        source_guide = await source.fetch_university_admission_guide(
            university_code=university.official_code,
            admission_year=source_admission_year,
        )
        verified_at = source.verified_at

    guide = await db.scalar(
        select(AdmissionUniversityGuide).where(
            AdmissionUniversityGuide.university_id == university.id,
            AdmissionUniversityGuide.source_admission_year == source_admission_year,
        )
    )
    if guide is None:
        guide = AdmissionUniversityGuide(
            university_id=university.id,
            source_admission_year=source_admission_year,
            sections=source_guide.sections,
            source_url=source_guide.source_url,
            verified_at=verified_at,
        )
        db.add(guide)
    else:
        guide.sections = source_guide.sections
        guide.source_url = source_guide.source_url
        guide.verified_at = verified_at
    await db.flush()
    return guide


async def sync_program_references_for_university(
    db: AsyncSession, university: University, source_admission_year: int
) -> int:
    """전년도 학과별 공개 경쟁률·모집인원 요약을 갱신한다."""
    async with AdigaCatalogSource() as source:
        source_rows = await source.fetch_program_references(
            university_code=university.official_code,
            admission_year=source_admission_year,
        )
        verified_at = source.verified_at

    existing = {
        row.source_reference_code: row
        for row in await db.scalars(
            select(AdmissionProgramReference).where(
                AdmissionProgramReference.university_id == university.id,
                AdmissionProgramReference.source_admission_year == source_admission_year,
            )
        )
    }
    for source_row in source_rows:
        source_url = (
            f"{BASE_URL}/ucp/cls/uni/classUnivDetail.do?menuId=PCCLSINF2000"
            f"&searchSyr={source_admission_year}&unvCd={university.official_code}"
            f"&ruCd={source_row.source_reference_code}"
        )
        row = existing.get(source_row.source_reference_code)
        if row is None:
            db.add(
                AdmissionProgramReference(
                    university_id=university.id,
                    source_admission_year=source_admission_year,
                    source_reference_code=source_row.source_reference_code,
                    name=source_row.name,
                    academic_field=source_row.academic_field,
                    recruitment_count=source_row.recruitment_count,
                    early_competition_rate=source_row.early_competition_rate,
                    regular_competition_rate=source_row.regular_competition_rate,
                    source_url=source_url,
                    verified_at=verified_at,
                )
            )
            continue
        row.name = source_row.name
        row.academic_field = source_row.academic_field
        row.recruitment_count = source_row.recruitment_count
        row.early_competition_rate = source_row.early_competition_rate
        row.regular_competition_rate = source_row.regular_competition_rate
        row.source_url = source_url
        row.verified_at = verified_at
    await db.flush()
    return len(source_rows)


async def sync_program_outcomes(
    db: AsyncSession, reference: AdmissionProgramReference, university: University
) -> int:
    """한 학과의 공개 입시결과를 현재 원천 응답으로 교체한다.

    결과 표는 매년 같은 학과·전형의 열 구성이 바뀔 수 있다. 동일한 원천 기준의
    이전 캐시만 지운 뒤 새 행을 넣어, 사용자 입력이나 다른 연도 데이터에는 손대지
    않는다.
    """
    async with AdigaCatalogSource() as source:
        source_url, source_rows = await source.fetch_program_outcomes(
            university_code=university.official_code,
            reference_code=reference.source_reference_code,
            admission_year=reference.source_admission_year,
        )
        verified_at = source.verified_at

    await db.execute(
        delete(AdmissionProgramOutcome).where(
            AdmissionProgramOutcome.program_reference_id == reference.id
        )
    )
    for source_row in source_rows:
        db.add(
            AdmissionProgramOutcome(
                program_reference_id=reference.id,
                recruitment_period=source_row.recruitment_period,
                selection_type=source_row.selection_type,
                selection_name=source_row.selection_name,
                initial_recruitment_count=source_row.initial_recruitment_count,
                transferred_recruitment_count=source_row.transferred_recruitment_count,
                final_recruitment_count=source_row.final_recruitment_count,
                competition_rate=source_row.competition_rate,
                additional_admission_count=source_row.additional_admission_count,
                metrics=source_row.metrics,
                source_url=source_url,
                verified_at=verified_at,
            )
        )
    reference.outcomes_checked_at = verified_at
    await db.flush()
    return len(source_rows)


async def sync_program_profile_sections(
    db: AsyncSession, reference: AdmissionProgramReference, university: University
) -> int:
    """학과 원문에서 교육목표·교육과정·진로 정보를 갱신한다."""
    async with AdigaCatalogSource() as source:
        source_url, sections = await source.fetch_program_profile_sections(
            university_code=university.official_code,
            reference_code=reference.source_reference_code,
            admission_year=reference.source_admission_year,
        )
        verified_at = source.verified_at
    reference.detail_sections = sections or None
    reference.profile_checked_at = verified_at
    reference.source_url = source_url
    reference.verified_at = verified_at
    await db.flush()
    return len(sections)
