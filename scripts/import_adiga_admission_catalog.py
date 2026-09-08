"""대입정보포털 일반대학 목록을 카탈로그에 반영한다.

사용 예시:
    uv run python scripts/import_adiga_admission_catalog.py

기본 실행은 일반대학 4년제 선택기의 대학 목록만 갱신한다. 모집단위는 사용자가
대학을 선택했을 때 해당 대학만 공식 포털에서 갱신하므로, 전체 포털에 수만 건의
불필요한 요청을 보내지 않는다.
"""

import asyncio
import sys
from pathlib import Path

# `uv run python scripts/...`에서도 프로젝트 패키지를 찾게 한다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import AsyncSessionLocal
from app.services.admission_catalog_service import sync_general_universities


async def main() -> None:
    async with AsyncSessionLocal() as db:
        count = await sync_general_universities(db)
        await db.commit()
    print(f"Imported {count} general universities from the official admissions portal.")


if __name__ == "__main__":
    asyncio.run(main())
