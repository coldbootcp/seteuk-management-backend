"""서울 주요대학의 대학 공통 대입특징·입시가이드를 적재한다.

현재 학년 자료가 비어 있으면 같은 공식 원천에서 바로 이전 학년을 차례로 찾아
가장 최근 정상 자료만 저장한다. 따라서 화면은 '확인 필요' 대신 실제 확인된
가이드를 그 학년도 표기와 함께 보여줄 수 있다.
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import or_, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import AsyncSessionLocal
from app.models.admission_catalog import University
from app.services.adiga_catalog_source import AdigaSourceError
from app.services.admission_catalog_service import sync_university_admission_guide

LATEST_SOURCE_ADMISSION_YEAR = 2027
OLDEST_SOURCE_ADMISSION_YEAR = 2024
REQUEST_INTERVAL_SECONDS = 0.5
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
                select(University)
                .where(University.name.in_(MAJOR_SEOUL_UNIVERSITIES))
                .where(or_(University.campus_name.is_(None), University.campus_name == "본교"))
                .order_by(University.name)
            )
        )
        for index, university in enumerate(universities, 1):
            guide = await _sync_latest_available_guide(db, university)
            await db.commit()
            if guide is None:
                print(
                    f"[{index}/{len(universities)}] {university.name}: "
                    f"no public guide ({OLDEST_SOURCE_ADMISSION_YEAR}-"
                    f"{LATEST_SOURCE_ADMISSION_YEAR})"
                )
            else:
                print(
                    f"[{index}/{len(universities)}] {university.name}: "
                    f"{guide.source_admission_year}, {len(guide.sections)} sections"
                )
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
