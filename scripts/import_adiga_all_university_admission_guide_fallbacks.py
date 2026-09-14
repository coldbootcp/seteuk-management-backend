"""최신 대학 가이드에서 빠진 탭을 보완할 이전 공개본을 적재한다.

2027학년도 어디가 페이지는 수시·정시 특징만 먼저 공개하는 경우가 많다. 2026부터
이전으로 내려가 전체 입시가이드 탭을 갖춘 가장 최근 자료를 별도 저장한다. 조회
API가 2027의 새 탭을 우선하고 이 자료의 누락 탭만 보완한다.
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import AsyncSessionLocal
from app.models.admission_catalog import University
from app.services.adiga_catalog_source import AdigaSourceError
from app.services.admission_catalog_service import sync_university_admission_guide

LATEST_FALLBACK_ADMISSION_YEAR = 2026
OLDEST_SOURCE_ADMISSION_YEAR = 2024
REQUEST_INTERVAL_SECONDS = 0.2


async def _sync_latest_fallback(db, university: University):
    for source_year in range(
        LATEST_FALLBACK_ADMISSION_YEAR, OLDEST_SOURCE_ADMISSION_YEAR - 1, -1
    ):
        try:
            return await sync_university_admission_guide(db, university, source_year)
        except AdigaSourceError:
            continue
    return None


async def main() -> None:
    async with AsyncSessionLocal() as db:
        universities = list(
            await db.scalars(
                select(University).where(University.is_active.is_(True)).order_by(University.name)
            )
        )
        for index, university in enumerate(universities, 1):
            guide = await _sync_latest_fallback(db, university)
            await db.commit()
            if guide is None:
                print(f"[{index}/{len(universities)}] {university.name}: no fallback guide")
            else:
                print(
                    f"[{index}/{len(universities)}] {university.name}: "
                    f"{guide.source_admission_year}, {len(guide.sections)} sections"
                )
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
