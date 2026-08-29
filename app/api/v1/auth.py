from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.auth import (
    AccessTokenResponse,
    KakaoLoginRequest,
    KakaoLoginResponse,
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


@router.post("/social/kakao", response_model=KakaoLoginResponse)
async def kakao_login(
    data: KakaoLoginRequest, db: Annotated[AsyncSession, Depends(get_db)]
) -> KakaoLoginResponse:
    access_token, refresh_token, is_new_user = await auth_service.kakao_login(
        db, data.kakao_access_token
    )
    return KakaoLoginResponse(
        access_token=access_token, refresh_token=refresh_token, is_new_user=is_new_user
    )


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    data: RefreshRequest, db: Annotated[AsyncSession, Depends(get_db)]
) -> AccessTokenResponse:
    access_token = await auth_service.refresh_access_token(db, data.refresh_token)
    return AccessTokenResponse(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(data: RefreshRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> None:
    """refresh 토큰을 무효화한다. 다른 기기의 세션은 유지된다."""
    await auth_service.logout(db, data.refresh_token)
