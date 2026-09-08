"""일반대학 전체의 대학 단위 공개 통계 스냅샷을 적재한다.

학과·전형별 결과와 달리, 이 작업은 대학별 차트 응답 하나만 호출한다. 따라서
전국 선택기에서 학교를 고른 직후에도 모집/지원 규모, 전형 분포, 취업률, 경쟁률의
공개 시계열을 바로 제공할 수 있다.
"""

import asyncio
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import AsyncSessionLocal
from app.models.admission_catalog import University
from app.services.adiga_catalog_source import AdigaSourceError
from app.services.admission_catalog_service import sync_university_statistics

SOURCE_ADMISSION_YEAR = 2026
REQUEST_INTERVAL_SECONDS = 0.15
MAX_RETRIES = 3


async def _sync_with_retry(db, university: University):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await sync_university_statistics(db, university, SOURCE_ADMISSION_YEAR)
        except (AdigaSourceError, httpx.HTTPError) as error:
            if attempt == MAX_RETRIES:
                print(f"skipped {university.name}: {type(error).__name__}")
                return None
            await asyncio.sleep(attempt)
    return None


async def main() -> None:
    async with AsyncSessionLocal() as db:
        universities = list(
            await db.scalars(
                select(University).where(University.is_active.is_(True)).order_by(University.name)
            )
        )
        for index, university in enumerate(universities, 1):
            snapshot = await _sync_with_retry(db, university)
            await db.commit()
            if snapshot is not None:
                series_count = sum(len(series) for series in snapshot.payload.values())
                print(f"[{index}/{len(universities)}] {university.name}: {series_count} statistics")
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
