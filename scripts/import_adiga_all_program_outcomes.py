"""아직 확인하지 않은 전국 학과의 전형별 공개 입시결과를 재개 가능하게 적재한다."""

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
from app.services.admission_catalog_service import sync_program_outcomes

SOURCE_ADMISSION_YEAR = 2026
REQUEST_INTERVAL_SECONDS = 0.35
MAX_RETRIES = 3


async def _sync_with_retry(
    db, reference: AdmissionProgramReference, university: University
) -> int | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await sync_program_outcomes(db, reference, university)
        except (AdigaSourceError, httpx.HTTPError) as error:
            if attempt == MAX_RETRIES:
                print(f"skipped {university.name} / {reference.name}: {type(error).__name__}")
                return None
            await asyncio.sleep(attempt)
    return None


async def main() -> None:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(AdmissionProgramReference, University)
                .join(University, AdmissionProgramReference.university_id == University.id)
                .where(
                    AdmissionProgramReference.source_admission_year == SOURCE_ADMISSION_YEAR,
                    AdmissionProgramReference.outcomes_checked_at.is_(None),
                )
                .order_by(University.name, AdmissionProgramReference.name)
            )
        ).all()
        for index, (reference, university) in enumerate(rows, 1):
            count = await _sync_with_retry(db, reference, university)
            await db.commit()
            if count is not None:
                print(
                    f"[{index}/{len(rows)}] {university.name} / {reference.name}: "
                    f"{count} outcomes"
                )
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
