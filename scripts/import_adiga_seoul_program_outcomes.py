"""서울 주요대학의 전년도 학과·전형별 공개 입시결과를 재시작 가능하게 적재한다."""

import asyncio
import sys
from pathlib import Path

import httpx
from sqlalchemy import or_, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import AsyncSessionLocal
from app.models.admission_catalog import University
from app.models.admission_program_reference import AdmissionProgramReference
from app.services.adiga_catalog_source import AdigaSourceError
from app.services.admission_catalog_service import sync_program_outcomes

SOURCE_ADMISSION_YEAR = 2026
REQUEST_INTERVAL_SECONDS = 0.45
MAX_RETRIES = 3
MAJOR_SEOUL_UNIVERSITIES = (
    "서울대학교",
    "연세대학교",
    "고려대학교",
    "서강대학교",
    "성균관대학교",
    "한양대학교",
    "중앙대학교",
    "경희대학교",
    "한국외국어대학교",
    "서울시립대학교",
    "이화여자대학교",
    "건국대학교",
    "동국대학교",
    "홍익대학교",
    "숙명여자대학교",
    "국민대학교",
    "숭실대학교",
    "세종대학교",
    "광운대학교",
    "서울과학기술대학교",
)


async def _sync_with_retry(
    db, reference: AdmissionProgramReference, university: University
) -> int:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await sync_program_outcomes(db, reference, university)
        except (AdigaSourceError, httpx.HTTPError) as error:
            if attempt == MAX_RETRIES:
                print(
                    f"  skipped after {MAX_RETRIES} attempts: "
                    f"{university.name} / {reference.name} ({type(error).__name__})"
                )
                return 0
            await asyncio.sleep(attempt)
    return 0


async def main() -> None:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(AdmissionProgramReference, University)
                .join(University, AdmissionProgramReference.university_id == University.id)
                .where(
                    AdmissionProgramReference.source_admission_year == SOURCE_ADMISSION_YEAR,
                    University.name.in_(MAJOR_SEOUL_UNIVERSITIES),
                    or_(
                        University.campus_name.is_(None),
                        University.campus_name == "본교",
                    ),
                )
                .order_by(University.name, AdmissionProgramReference.name)
            )
        ).all()
        total_outcomes = 0
        for index, (reference, university) in enumerate(rows, 1):
            outcome_count = await _sync_with_retry(db, reference, university)
            total_outcomes += outcome_count
            await db.commit()
            print(
                f"[{index}/{len(rows)}] {university.name} / {reference.name}: "
                f"{outcome_count} outcomes (total {total_outcomes})"
            )
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
