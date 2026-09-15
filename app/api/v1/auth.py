from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import enforce_auth_rate_limit
from app.db.session import get_db
from app.schemas.auth import (
    AccessTokenResponse,
    ForgotPasswordRequest,
    GoogleLoginRequest,
    GoogleLoginResponse,
    KakaoLoginRequest,
    KakaoLoginResponse,
    LoginRequest,
    MessageResponse,
    RefreshRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    SignupRequest,
    SignupResponse,
    TokenPairResponse,
    VerifyEmailRequest,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

# 이메일 존재 여부가 새어 나가지 않도록, 재발송·비밀번호 재설정 요청은 항상
# 같은 메시지를 돌려준다(OWASP User Enumeration 방지).
_GENERIC_EMAIL_SENT_MESSAGE = "해당 이메일로 가입된 계정이 있다면 메일을 보냈습니다"


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    data: SignupRequest, request: Request, db: Annotated[AsyncSession, Depends(get_db)]
) -> SignupResponse:
    await enforce_auth_rate_limit(
        db, f"ip:{_client_ip(request)}", "signup", limit=10, window=timedelta(hours=1)
    )
    user, access_token, refresh_token = await auth_service.signup(db, data)
    return SignupResponse(user_id=user.id, access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=TokenPairResponse)
async def login(
    data: LoginRequest, request: Request, db: Annotated[AsyncSession, Depends(get_db)]
) -> TokenPairResponse:
    # 이메일별로도, IP별로도 건다 — 하나의 IP로 여러 계정을 두드리는 것과
    # 여러 IP로 한 계정을 두드리는 것을 둘 다 늦춘다.
    await enforce_auth_rate_limit(
        db, f"email:{data.email}", "login", limit=10, window=timedelta(minutes=15)
    )
    await enforce_auth_rate_limit(
        db, f"ip:{_client_ip(request)}", "login", limit=30, window=timedelta(minutes=15)
    )
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


@router.post("/social/google", response_model=GoogleLoginResponse)
async def google_login(
    data: GoogleLoginRequest, db: Annotated[AsyncSession, Depends(get_db)]
) -> GoogleLoginResponse:
    access_token, refresh_token, is_new_user = await auth_service.google_login(
        db, data.google_access_token
    )
    return GoogleLoginResponse(
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


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
    data: VerifyEmailRequest, db: Annotated[AsyncSession, Depends(get_db)]
) -> MessageResponse:
    await auth_service.verify_email(db, data.token)
    return MessageResponse(message="이메일 인증이 완료되었습니다")


@router.post("/resend-verification", response_model=MessageResponse)
async def resend_verification(
    data: ResendVerificationRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    await enforce_auth_rate_limit(
        db, f"email:{data.email}", "resend_verification", limit=3, window=timedelta(hours=1)
    )
    await auth_service.resend_verification_email(db, data.email)
    return MessageResponse(message=_GENERIC_EMAIL_SENT_MESSAGE)


@router.post("/password/forgot", response_model=MessageResponse)
async def forgot_password(
    data: ForgotPasswordRequest, request: Request, db: Annotated[AsyncSession, Depends(get_db)]
) -> MessageResponse:
    await enforce_auth_rate_limit(
        db, f"email:{data.email}", "password_forgot", limit=3, window=timedelta(hours=1)
    )
    await enforce_auth_rate_limit(
        db, f"ip:{_client_ip(request)}", "password_forgot", limit=10, window=timedelta(hours=1)
    )
    await auth_service.request_password_reset(db, data.email)
    return MessageResponse(message=_GENERIC_EMAIL_SENT_MESSAGE)


@router.post("/password/reset", response_model=MessageResponse)
async def reset_password(
    data: ResetPasswordRequest, db: Annotated[AsyncSession, Depends(get_db)]
) -> MessageResponse:
    await auth_service.reset_password(db, data.token, data.new_password)
    return MessageResponse(message="비밀번호가 변경되었습니다. 다시 로그인해주세요")
