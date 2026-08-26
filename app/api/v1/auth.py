from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenType, create_access_token, decode_token
from app.db.session import get_db
from app.schemas.auth import (
    AccessTokenResponse,
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
    TokenPairResponse,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    data: SignupRequest, db: Annotated[AsyncSession, Depends(get_db)]
) -> SignupResponse:
    user, access_token, refresh_token = await auth_service.signup(db, data)
    return SignupResponse(user_id=user.id, access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=TokenPairResponse)
async def login(
    data: LoginRequest, db: Annotated[AsyncSession, Depends(get_db)]
) -> TokenPairResponse:
    access_token, refresh_token = await auth_service.login(db, data)
    return TokenPairResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(data: RefreshRequest) -> AccessTokenResponse:
    user_id = decode_token(data.refresh_token, TokenType.REFRESH)
    return AccessTokenResponse(access_token=create_access_token(user_id))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> None:
    return None
