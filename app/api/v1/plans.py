import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.rate_limit import enforce_daily_limit
from app.db.session import get_db
from app.models.plan_item import PlanItem
from app.models.usage_event import UsageAction
from app.models.user import User
from app.schemas.plan import (
    PlanItemCompleteRequest,
    PlanItemCompleteResponse,
    PlanItemCreate,
    PlanItemRead,
    PlanItemUpdate,
    RoadmapGenerateRequest,
    RoadmapOverview,
    RoadmapResponse,
)
from app.schemas.records import ListResponse
from app.services import plan_service, record_service

router = APIRouter(prefix="/plans", tags=["plans"])


class PlanFilters(BaseModel):
    limit: int = Field(default=100, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    item_type: str | None = None
    status: str | None = None
    target_grade: int | None = None
    target_semester: int | None = None


@router.get("", response_model=ListResponse[PlanItemRead])
async def list_plans(
    filters: Annotated[PlanFilters, Query()],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ListResponse[PlanItemRead]:
    rows, total = await record_service.list_records(
        db,
        PlanItem,
        user.id,
        filters=filters.model_dump(exclude={"limit", "offset"}),
        order_by=[
            PlanItem.target_grade.asc().nullslast(),
            PlanItem.target_semester.asc().nullslast(),
            PlanItem.created_at.asc(),
        ],
        limit=filters.limit,
        offset=filters.offset,
    )
    return ListResponse[PlanItemRead](
        items=[PlanItemRead.model_validate(row) for row in rows], total=total
    )


@router.post("", response_model=PlanItemRead, status_code=status.HTTP_201_CREATED)
async def create_plan(
    data: PlanItemCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlanItemRead:
    plan = await plan_service.create_plan_item(db, user.id, data)
    return PlanItemRead.model_validate(plan)


@router.post("/roadmap", response_model=RoadmapResponse)
async def generate_roadmap(
    data: RoadmapGenerateRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RoadmapResponse:
    """남은 학기들에 대한 AI 로드맵을 생성하고, 각 항목을 계획으로 저장한다."""
    await enforce_daily_limit(db, user.id, UsageAction.ROADMAP)
    semesters, created = await plan_service.generate_roadmap(db, user, data)
    return RoadmapResponse(
        semesters=semesters,
        created_plan_items=[PlanItemRead.model_validate(p) for p in created],
    )


@router.get("/roadmap-overview", response_model=RoadmapOverview)
async def get_roadmap_overview(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RoadmapOverview:
    """3개년 그랜드 로드맵 — 새 LLM 호출 없이, 이미 있는 진단과 계획을
    과거/현재/미래 마일스톤으로 재배치만 한다. /plans/{plan_id}보다 먼저 등록해야
    "roadmap-overview"가 plan_id로 잘못 매칭되지 않는다."""
    return await plan_service.get_roadmap_overview(db, user)


@router.get("/{plan_id}", response_model=PlanItemRead)
async def get_plan(
    plan_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlanItemRead:
    plan = await plan_service.get_plan_item(db, user.id, plan_id)
    return PlanItemRead.model_validate(plan)


@router.patch("/{plan_id}", response_model=PlanItemRead)
async def update_plan(
    plan_id: uuid.UUID,
    data: PlanItemUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlanItemRead:
    plan = await plan_service.update_plan_item(
        db, user.id, plan_id, data.model_dump(exclude_unset=True)
    )
    return PlanItemRead.model_validate(plan)


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(
    plan_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await plan_service.delete_plan_item(db, user.id, plan_id)


@router.post("/{plan_id}/complete", response_model=PlanItemCompleteResponse)
async def complete_plan(
    plan_id: uuid.UUID,
    data: PlanItemCompleteRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlanItemCompleteResponse:
    """계획을 실제 기록으로 승격 — 활동/독서 탭에 행이 생기고 계보가 이어진다."""
    plan = await plan_service.complete_plan_item(db, user, plan_id, data)
    return PlanItemCompleteResponse(
        plan_item=PlanItemRead.model_validate(plan),
        created_activity_id=plan.completed_activity_id,
        created_reading_id=plan.completed_reading_id,
    )
