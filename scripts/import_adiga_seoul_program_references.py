"""서울 주요대학의 전년도 학과별 모집·경쟁률 요약을 적재한다."""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import or_, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import AsyncSessionLocal
from app.models.admission_catalog import University
from app.services.adiga_catalog_source import AdigaSourceError
from app.services.admission_catalog_service import sync_program_references_for_university

SOURCE_ADMISSION_YEAR = 2026
REQUEST_INTERVAL_SECONDS = 0.6
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


async def _sync_with_retry(db, university: University) -> int:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await sync_program_references_for_university(
                db, university, SOURCE_ADMISSION_YEAR
            )
        except AdigaSourceError as error:
            if attempt == MAX_RETRIES:
                print(f"  skipped after {MAX_RETRIES} attempts: {university.name} ({error})")
                return 0
            await asyncio.sleep(attempt)
    return 0


async def main() -> None:
    async with AsyncSessionLocal() as db:
        universities = list(
            await db.scalars(
                select(University)
                .where(University.name.in_(MAJOR_SEOUL_UNIVERSITIES))
                .where(
                    or_(
                        University.campus_name.is_(None),
                        University.campus_name == "본교",
                    )
                )
                .order_by(University.name)
            )
        )
        for index, university in enumerate(universities, 1):
            count = await _sync_with_retry(db, university)
            await db.commit()
            print(f"[{index}/{len(universities)}] {university.name}: {count} program references")
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
