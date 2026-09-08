"""대입정보포털에서 서울 주요대학의 모집단위·전형을 재시작 가능하게 적재한다.

사용 예시:
    uv run python scripts/import_adiga_seoul_major_catalog.py

대학 하나가 끝날 때마다 커밋한다. 중단 후 같은 명령을 다시 실행해도 원천 코드와
표시명을 기준으로 갱신하므로 중복 행을 만들지 않는다. 포털 과부하를 피하기 위해
전형 요청 사이에 짧은 간격을 둔다.
"""

import asyncio
import sys
from pathlib import Path

import httpx
from sqlalchemy import or_, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import AsyncSessionLocal
from app.models.admission_catalog import AdmissionProgram, University
from app.services.adiga_catalog_source import AdigaSourceError
from app.services.admission_catalog_service import (
    sync_programs_for_university,
    sync_tracks_for_program,
)

ADMISSION_YEAR = 2027
REQUEST_INTERVAL_SECONDS = 0.25
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


async def _retry(operation, label: str) -> int:
    """포털의 일시 오류로 전체 수집이 멈추지 않게, 짧게 재시도한다."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await operation()
        except (AdigaSourceError, httpx.HTTPError) as error:
            if attempt == MAX_RETRIES:
                print(f"  skipped after {MAX_RETRIES} attempts: {label} ({type(error).__name__})")
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
        print(f"Collecting {len(universities)} universities for {ADMISSION_YEAR}.")
        for university_index, university in enumerate(universities, 1):
            program_count = await _retry(
                lambda university=university: sync_programs_for_university(
                    db, university, ADMISSION_YEAR
                ),
                university.name,
            )
            await db.commit()
            programs = list(
                await db.scalars(
                    select(AdmissionProgram)
                    .where(AdmissionProgram.university_id == university.id)
                    .where(AdmissionProgram.admission_year == ADMISSION_YEAR)
                    .where(AdmissionProgram.is_recruiting.is_(True))
                    .order_by(AdmissionProgram.name)
                )
            )
            track_count = 0
            for program in programs:
                track_count += await _retry(
                    lambda program=program: sync_tracks_for_program(db, program),
                    f"{university.name} / {program.name}",
                )
                await db.commit()
                await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
            print(
                f"[{university_index}/{len(universities)}] {university.name}: "
                f"{program_count} programs, {track_count} tracks"
            )


if __name__ == "__main__":
    asyncio.run(main())
