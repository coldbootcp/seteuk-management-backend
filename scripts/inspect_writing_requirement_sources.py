"""전국 수시모집요강 원문을 사전 점검한다.

공식 파일 URL과 판독 메타데이터만 DB에 보관하며, PDF 전문·학생 파일은 저장하지
않는다. 기본값은 요청 부담을 줄인 12곳이므로 전국 실행은 명시적으로 --all을 쓴다.
"""

import argparse
import asyncio
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import AsyncSessionLocal
from app.models.admission_catalog import University
from app.models.admission_writing_source_document import AdmissionWritingSourceDocument
from app.services.writing_requirement_source import (
    AdmissionGuide,
    WritingRequirementSource,
    WritingRequirementSourceError,
)


async def _save_result(
    *, guide: AdmissionGuide, source: WritingRequirementSource, semaphore: asyncio.Semaphore
) -> tuple[str, AdmissionGuide, dict[str, object]]:
    async with semaphore:
        try:
            inspection = await source.inspect_guide(guide)
            return (
                "inspected",
                guide,
                {
                    "has_writing_marker": bool(inspection.marker_contexts),
                    "marker_count": len(inspection.marker_contexts),
                    "inspection_note": "공식 수시모집요강 텍스트 PDF를 판독했습니다.",
                    "inspected_at": inspection.inspected_at,
                },
            )
        except (WritingRequirementSourceError, httpx.HTTPError, ValueError) as error:
            return (
                "unreadable",
                guide,
                {"inspection_note": str(error), "has_writing_marker": None, "marker_count": None},
            )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2027)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()

    async with WritingRequirementSource() as source:
        guides = await source.fetch_susi_guides(admission_year=args.year)
        if not args.all:
            guides = guides[: args.limit]
        semaphore = asyncio.Semaphore(3)
        results = await asyncio.gather(
            *(_save_result(guide=guide, source=source, semaphore=semaphore) for guide in guides)
        )

    async with AsyncSessionLocal() as db:
        university_rows = await db.scalars(
            select(University).where(University.is_active.is_(True))
        )
        universities = {row.official_code: row for row in university_rows.all()}
        saved = 0
        for inspection_status, guide, values in results:
            university = universities.get(guide.university_code)
            if not university:
                continue
            row = await db.scalar(
                select(AdmissionWritingSourceDocument).where(
                    AdmissionWritingSourceDocument.university_id == university.id,
                    AdmissionWritingSourceDocument.source_admission_year == guide.admission_year,
                )
            )
            if row is None:
                row = AdmissionWritingSourceDocument(
                    university_id=university.id,
                    source_admission_year=guide.admission_year,
                    title=guide.title,
                    source_url=guide.source_url,
                    inspection_status=inspection_status,
                )
                db.add(row)
            row.title = guide.title
            row.source_url = guide.source_url
            row.inspection_status = inspection_status
            row.has_writing_marker = values["has_writing_marker"]  # type: ignore[assignment]
            row.marker_count = values["marker_count"]  # type: ignore[assignment]
            row.inspection_note = values["inspection_note"]  # type: ignore[assignment]
            row.inspected_at = values.get("inspected_at")  # type: ignore[assignment]
            saved += 1
        await db.commit()
    print(f"Inspected {saved} official {args.year} 수시모집요강 files.")


if __name__ == "__main__":
    asyncio.run(main())
