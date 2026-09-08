"""일반대학 전체의 해당 입학연도 모집단위를 미리 적재한다.

전형은 학과마다 여러 개라 전국 일괄 수집 시 포털에 과도한 요청이 생긴다. 반면
모집단위 목록은 대학당 한 번의 공식 조회로 끝나므로, 학교·학과 자동완성의 기반을
먼저 전국으로 넓힌다. 전형 상세는 선택 시점 또는 별도 배치에서만 확장한다.
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
from app.services.admission_catalog_service import sync_programs_for_university

ADMISSION_YEAR = 2027
REQUEST_INTERVAL_SECONDS = 0.2
MAX_RETRIES = 3


async def _sync_with_retry(db, university: University) -> int:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await sync_programs_for_university(db, university, ADMISSION_YEAR)
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
                select(University).where(University.is_active.is_(True)).order_by(University.name)
            )
        )
        for index, university in enumerate(universities, 1):
            count = await _sync_with_retry(db, university)
            await db.commit()
            print(f"[{index}/{len(universities)}] {university.name}: {count} programs")
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
