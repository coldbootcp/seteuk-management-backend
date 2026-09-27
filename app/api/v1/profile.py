from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_active_verified_user, get_current_user
from app.core.rate_limit import enforce_daily_limit
from app.db.session import get_db
from app.models.usage_event import UsageAction
from app.models.user import User
from app.schemas.profile import (
    ProfileRequest,
    ProfileResponse,
    SuggestRequest,
    SuggestResponse,
)
from app.services import profile_service

router = APIRouter(
    prefix="/profile", tags=["profile"], dependencies=[Depends(get_active_verified_user)]
)


@router.post("", response_model=ProfileResponse)
async def set_profile(
    data: ProfileRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProfileResponse:
    await profile_service.set_profile(db, user, data)
    return await profile_service.get_profile(db, user)


@router.get("/me", response_model=ProfileResponse)
async def get_profile(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProfileResponse:
    return await profile_service.get_profile(db, user)


@router.post("/suggest", response_model=SuggestResponse)
async def suggest_direction(
    data: SuggestRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SuggestResponse:
    """진로 희망 문구로 학과 후보와 관심 키워드를 제안한다. 저장하지 않는다 —
    학생이 고른 값만 POST /profile로 확정된다."""
    await enforce_daily_limit(db, user.id, UsageAction.CHAT_MESSAGE)
    return await profile_service.suggest_direction(data.career_goal)
