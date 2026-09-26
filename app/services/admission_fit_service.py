"""졸업생(수시 재수생) 적합성 상담이 쓰는 학과 조회.

상담 챗봇이 "이 생기부로 이 학과에 현실적으로 승산이 있는가"를 감이 아니라
공개된 어디가 데이터(모집인원·경쟁률·교육목표·진로)를 근거로 말하도록, 목표
학과 이름으로 admission_program_references를 찾아 요약해 준다.

수치를 지어내지 않는다 — 찾지 못하면 빈 결과를 정직하게 돌려주고, 챗봇이
"확인된 데이터가 없다"고 말하게 한다.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admission_catalog import University
from app.models.admission_program_reference import (
    AdmissionProgramOutcome,
    AdmissionProgramReference,
)

# 한 번의 조회로 챗봇에 넘길 학과 후보 수. 여러 대학이 섞이면 챗봇이 학생에게
# 어느 대학인지 되물어 좁히도록, 너무 많이 주지 않는다.
_PROGRAM_LIMIT = 8
# 학과당 최근 입시결과 행 수. 전형이 많은 학과도 있어 상한을 둔다.
_OUTCOME_LIMIT = 6


async def search_program_fit(
    db: AsyncSession,
    *,
    department_query: str,
    university_query: str | None = None,
) -> dict:
    """목표 학과 이름(+선택적으로 대학 이름)으로 공개 학과 정보를 찾아 요약한다.

    반환 형태는 챗봇이 그대로 근거로 삼을 수 있는 요약 dict다. 확인된 학과가
    없으면 programs를 빈 리스트로 돌려주고, 챗봇은 이를 "데이터 없음"으로 다뤄야
    한다(수치를 추측하지 마라).
    """
    query = (department_query or "").strip()
    if not query:
        return {"query": department_query, "programs": [], "note": "학과 이름이 비어 있습니다."}

    statement = (
        select(AdmissionProgramReference, University.name)
        .join(University, University.id == AdmissionProgramReference.university_id)
        .where(AdmissionProgramReference.name.ilike(f"%{query}%"))
    )
    if university_query and university_query.strip():
        statement = statement.where(University.name.ilike(f"%{university_query.strip()}%"))
    # 최신 학년도를 우선 보여준다.
    statement = statement.order_by(
        AdmissionProgramReference.source_admission_year.desc(),
        University.name,
    ).limit(_PROGRAM_LIMIT)

    rows = list(await db.execute(statement))
    if not rows:
        return {
            "query": department_query,
            "university_query": university_query,
            "programs": [],
            "note": "공개된 어디가 데이터에서 해당 학과를 찾지 못했습니다.",
        }

    programs = []
    for reference, university_name in rows:
        outcomes = await _recent_outcomes(db, reference.id)
        programs.append(
            {
                "university": university_name,
                "program": reference.name,
                "academic_field": reference.academic_field,
                "admission_year": reference.source_admission_year,
                "recruitment_count": reference.recruitment_count,
                "early_competition_rate": reference.early_competition_rate,
                "regular_competition_rate": reference.regular_competition_rate,
                # 교육목표·인재상·진로 등. 공개 안 된 학과는 None.
                "detail_sections": reference.detail_sections,
                "recent_outcomes": outcomes,
                "source_url": reference.source_url,
            }
        )

    return {
        "query": department_query,
        "university_query": university_query,
        "programs": programs,
    }


async def _recent_outcomes(db: AsyncSession, reference_id: uuid.UUID) -> list[dict]:
    outcomes = await db.scalars(
        select(AdmissionProgramOutcome)
        .where(AdmissionProgramOutcome.program_reference_id == reference_id)
        .order_by(AdmissionProgramOutcome.created_at.desc())
        .limit(_OUTCOME_LIMIT)
    )
    return [
        {
            "recruitment_period": o.recruitment_period,
            "selection_type": o.selection_type,
            "selection_name": o.selection_name,
            "final_recruitment_count": o.final_recruitment_count,
            "competition_rate": o.competition_rate,
            "additional_admission_count": o.additional_admission_count,
            # 대학마다 지표 종류가 달라 단일 커트라인으로 뭉치지 않고 그대로 넘긴다.
            "metrics": o.metrics,
        }
        for o in outcomes
    ]
