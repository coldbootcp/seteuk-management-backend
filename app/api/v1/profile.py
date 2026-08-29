from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.profile import ProfileRequest, ProfileResponse
from app.services import profile_service

router = APIRouter(prefix="/profile", tags=["profile"])


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
