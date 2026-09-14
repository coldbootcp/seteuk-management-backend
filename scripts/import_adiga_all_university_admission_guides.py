"""일반대학 전체의 대학 공통 대입특징·입시가이드를 적재한다.

현재 학년도에 수시·정시 탭만 먼저 공개되는 대학도 있으므로, 각 대학에서 2027부터
2024까지 차례로 확인한다. 조회 API는 최신 탭을 우선하고 없는 탭만 이전 공개본으로
보완하며, 응답 섹션마다 실제 기준 학년도를 표시한다.
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

LATEST_SOURCE_ADMISSION_YEAR = 2027
OLDEST_SOURCE_ADMISSION_YEAR = 2024
REQUEST_INTERVAL_SECONDS = 0.2


async def _sync_latest_available_guide(db, university: University):
    for source_year in range(LATEST_SOURCE_ADMISSION_YEAR, OLDEST_SOURCE_ADMISSION_YEAR - 1, -1):
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
            guide = await _sync_latest_available_guide(db, university)
            await db.commit()
            if guide is None:
                print(f"[{index}/{len(universities)}] {university.name}: no public guide")
            else:
                print(
                    f"[{index}/{len(universities)}] {university.name}: "
                    f"{guide.source_admission_year}, {len(guide.sections)} sections"
                )
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
