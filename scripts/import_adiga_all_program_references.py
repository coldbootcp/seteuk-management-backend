"""일반대학 전체의 전년도 학과별 모집·경쟁률 기준 행을 적재한다."""

import asyncio
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import AsyncSessionLocal
from app.models.admission_catalog import University
from app.models.admission_program_reference import AdmissionProgramReference
from app.services.adiga_catalog_source import AdigaSourceError
from app.services.admission_catalog_service import sync_program_references_for_university

SOURCE_ADMISSION_YEAR = 2026
REQUEST_INTERVAL_SECONDS = 0.3
MAX_RETRIES = 3


async def _sync_with_retry(db, university: University) -> int:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await sync_program_references_for_university(
                db, university, SOURCE_ADMISSION_YEAR
            )
        except (AdigaSourceError, httpx.HTTPError) as error:
            if attempt == MAX_RETRIES:
                print(f"skipped {university.name}: {type(error).__name__}")
                return 0
            await asyncio.sleep(attempt)
    return 0


async def main() -> None:
    async with AsyncSessionLocal() as db:
        universities = list(
            await db.scalars(
                select(University)
                .where(
                    University.is_active.is_(True),
                    ~select(AdmissionProgramReference.id)
                    .where(
                        AdmissionProgramReference.university_id == University.id,
                        AdmissionProgramReference.source_admission_year == SOURCE_ADMISSION_YEAR,
                    )
                    .exists(),
                )
                .order_by(University.name)
            )
        )
        for index, university in enumerate(universities, 1):
            count = await _sync_with_retry(db, university)
            await db.commit()
            print(f"[{index}/{len(universities)}] {university.name}: {count} references")
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
