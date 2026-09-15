"""지원처별 자소서 설계 API."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_active_verified_user, get_current_user
from app.db.session import get_db
from app.models.application_preparation import ApplicationPreparation
from app.models.user import User
from app.schemas.application_preparation import (
    ActivityFlowRead,
    ApplicationPreparationCreate,
    ApplicationPreparationRead,
    ApplicationPreparationUpdate,
    PreparationActivityRecommendationRead,
)
from app.services import application_preparation_service

router = APIRouter(
    prefix="/application-preparations",
    tags=["application-preparations"],
    dependencies=[Depends(get_active_verified_user)],
)


@router.get("/activity-flows", response_model=list[ActivityFlowRead])
async def activity_flows(
    user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]
):
    return await application_preparation_service.list_activity_flows(db, user.id)


@router.get("", response_model=list[ApplicationPreparationRead])
async def list_preparations(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    entries = list(
        await db.scalars(
            select(ApplicationPreparation)
            .where(ApplicationPreparation.user_id == user.id)
            .order_by(ApplicationPreparation.updated_at.desc())
        )
    )
    return [
        await application_preparation_service.read_preparation(db, user.id, entry)
        for entry in entries
    ]


@router.post("", response_model=ApplicationPreparationRead, status_code=status.HTTP_201_CREATED)
async def create_preparation(
    data: ApplicationPreparationCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        entry = await application_preparation_service.create_preparation(db, user.id, data)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    return await application_preparation_service.read_preparation(db, user.id, entry)


@router.post(
    "/{preparation_id}/activity-recommendations",
    response_model=PreparationActivityRecommendationRead,
)
async def recommend_activities(
    preparation_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await application_preparation_service.recommend_activities_for_preparation(
        db, user.id, preparation_id
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="지원 설계를 찾을 수 없습니다."
        )
    return result


@router.get("/{preparation_id}", response_model=ApplicationPreparationRead)
async def get_preparation(
    preparation_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    entry = await db.scalar(
        select(ApplicationPreparation).where(
            ApplicationPreparation.id == preparation_id, ApplicationPreparation.user_id == user.id
        )
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="지원 설계를 찾을 수 없습니다."
        )
    return await application_preparation_service.read_preparation(db, user.id, entry)


@router.delete("/{preparation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preparation(
    preparation_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    deleted = await application_preparation_service.delete_preparation(db, user.id, preparation_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="지원 카드를 찾을 수 없습니다."
        )


@router.put("/{preparation_id}", response_model=ApplicationPreparationRead)
async def update_preparation(
    preparation_id: uuid.UUID,
    data: ApplicationPreparationUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        entry = await application_preparation_service.update_preparation(
            db, user.id, preparation_id, data
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="지원 설계를 찾을 수 없습니다."
        )
    return await application_preparation_service.read_preparation(db, user.id, entry)
