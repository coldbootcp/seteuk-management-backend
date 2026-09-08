"""서울 주요대학의 대학 단위 공개 입시 통계 스냅샷을 적재한다.

모집단위·전형 목록과 별개로, 어디가가 공개한 대학 전체 모집/지원 인원,
경쟁률, 전형유형 분포, 취업률 시계열을 2026학년도 기준 스냅샷으로 보관한다.
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import or_, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import AsyncSessionLocal
from app.models.admission_catalog import University
from app.services.admission_catalog_service import sync_university_statistics

SOURCE_ADMISSION_YEAR = 2026
REQUEST_INTERVAL_SECONDS = 0.4
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
            row = await sync_university_statistics(db, university, SOURCE_ADMISSION_YEAR)
            await db.commit()
            print(
                f"[{index}/{len(universities)}] {university.name}: "
                f"{sum(len(series) for series in row.payload.values())} statistics"
            )
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
