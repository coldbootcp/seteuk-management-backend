import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.rate_limit import enforce_daily_limit
from app.db.session import get_db
from app.models.recommendation import Recommendation
from app.models.usage_event import UsageAction
from app.models.user import User
from app.schemas.plan import PlanItemRead
from app.schemas.recommendation import (
    AdoptOptionRequest,
    FollowUpRequest,
    RecommendationRead,
)
from app.schemas.records import ListResponse
from app.services import recommendation_service, record_service

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


class RecommendationFilters(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    source_activity_id: uuid.UUID | None = None


@router.post("/follow-up", response_model=RecommendationRead, status_code=status.HTTP_201_CREATED)
async def create_follow_up(
    data: FollowUpRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RecommendationRead:
    await enforce_daily_limit(db, user.id, UsageAction.RECOMMENDATION)
    recommendation = await recommendation_service.create_follow_up(db, user, data)
    return RecommendationRead.model_validate(recommendation)


@router.get("", response_model=ListResponse[RecommendationRead])
async def list_recommendations(
    filters: Annotated[RecommendationFilters, Query()],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ListResponse[RecommendationRead]:
    rows, total = await record_service.list_records(
        db,
        Recommendation,
        user.id,
        filters=filters.model_dump(exclude={"limit", "offset"}),
        order_by=[Recommendation.created_at.desc()],
        limit=filters.limit,
        offset=filters.offset,
    )
    return ListResponse[RecommendationRead](
        items=[RecommendationRead.model_validate(row) for row in rows], total=total
    )


@router.get("/{recommendation_id}", response_model=RecommendationRead)
async def get_recommendation(
    recommendation_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RecommendationRead:
    recommendation = await recommendation_service.get_recommendation(
        db, user.id, recommendation_id
    )
    return RecommendationRead.model_validate(recommendation)


@router.post("/{recommendation_id}/adopt", response_model=PlanItemRead, status_code=201)
async def adopt_option(
    recommendation_id: uuid.UUID,
    data: AdoptOptionRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlanItemRead:
    """추천 선택지를 계획 탭으로 담아 '추천 → 계획 → 실행 → 기록' 루프를 잇는다."""
    plan = await recommendation_service.adopt_option(db, user, recommendation_id, data)
    return PlanItemRead.model_validate(plan)
