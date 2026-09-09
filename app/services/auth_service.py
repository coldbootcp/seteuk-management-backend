import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    InvalidTokenError,
    SocialAuthError,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    refresh_token_expiry,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import LoginRequest, SignupRequest

settings = get_settings()

KAKAO_USER_INFO_URL = "https://kapi.kakao.com/v2/user/me"
KAKAO_TIMEOUT_SECONDS = 10


async def issue_token_pair(db: AsyncSession, user_id: uuid.UUID) -> tuple[str, str]:
    """access는 무상태로 두고, refresh만 DB에 남겨 무효화할 수 있게 한다."""
    entry = RefreshToken(user_id=user_id, expires_at=refresh_token_expiry())
    db.add(entry)
    await db.commit()
    return create_access_token(user_id), create_refresh_token(user_id, entry.id)


async def signup(db: AsyncSession, data: SignupRequest) -> tuple[User, str, str]:
    existing = await db.scalar(select(User).where(User.email == data.email))
    if existing is not None:
        raise EmailAlreadyExistsError("이미 가입된 이메일입니다")

    user = User(email=data.email, password_hash=hash_password(data.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)

    access_token, refresh_token = await issue_token_pair(db, user.id)
    return user, access_token, refresh_token


async def login(db: AsyncSession, data: LoginRequest) -> tuple[str, str]:
    user = await db.scalar(select(User).where(User.email == data.email))
    if user is None or user.password_hash is None:
        raise InvalidCredentialsError("이메일 또는 비밀번호가 올바르지 않습니다")

    if not verify_password(data.password, user.password_hash):
        raise InvalidCredentialsError("이메일 또는 비밀번호가 올바르지 않습니다")

    return await issue_token_pair(db, user.id)


async def _load_active_refresh_token(db: AsyncSession, token: str) -> RefreshToken:
    user_id, jti = decode_refresh_token(token)
    entry = await db.get(RefreshToken, jti)
    if entry is None or entry.user_id != user_id or entry.revoked_at is not None:
        raise InvalidTokenError("만료되었거나 무효한 토큰입니다")
    return entry


async def refresh_access_token(db: AsyncSession, token: str) -> str:
    entry = await _load_active_refresh_token(db, token)
    return create_access_token(entry.user_id)


async def logout(db: AsyncSession, token: str) -> None:
    """해당 refresh 토큰만 무효화한다 — 다른 기기의 세션은 살려 둔다.
    이미 무효화된 토큰으로 다시 로그아웃해도 조용히 통과시킨다(멱등)."""
    try:
        user_id, jti = decode_refresh_token(token)
    except InvalidTokenError:
        return

    entry = await db.get(RefreshToken, jti)
    if entry is not None and entry.user_id == user_id and entry.revoked_at is None:
        entry.revoked_at = datetime.now(UTC)
        await db.commit()


async def _fetch_kakao_profile(kakao_access_token: str) -> tuple[str, str | None]:
    async with httpx.AsyncClient(timeout=KAKAO_TIMEOUT_SECONDS) as client:
        try:
            response = await client.get(
                KAKAO_USER_INFO_URL,
                headers={"Authorization": f"Bearer {kakao_access_token}"},
            )
        except httpx.HTTPError as exc:
            raise SocialAuthError(f"카카오 서버에 연결하지 못했습니다: {exc}") from exc

    if response.status_code != 200:
        raise SocialAuthError("카카오 토큰이 유효하지 않습니다")

    payload = response.json()
    kakao_id = payload.get("id")
    if kakao_id is None:
        raise SocialAuthError("카카오 응답에서 사용자 식별자를 찾지 못했습니다")

    # 이메일은 사용자가 제공에 동의해야만 내려온다 — 없어도 가입은 되어야 한다.
    email = (payload.get("kakao_account") or {}).get("email")
    return str(kakao_id), email


async def kakao_login(db: AsyncSession, kakao_access_token: str) -> tuple[str, str, bool]:
    kakao_id, email = await _fetch_kakao_profile(kakao_access_token)

    user = await db.scalar(select(User).where(User.kakao_id == kakao_id))
    is_new_user = False

    if user is None and email:
        # 같은 이메일로 이미 가입해 둔 계정이 있으면 새로 만들지 않고 연결한다.
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            user.kakao_id = kakao_id

    if user is None:
        # 이메일 동의를 안 한 사용자를 위해 카카오 id 기반 placeholder를 쓴다.
        user = User(email=email or f"kakao_{kakao_id}@kakao.local", kakao_id=kakao_id)
        db.add(user)
        is_new_user = True

    await db.commit()
    await db.refresh(user)

    access_token, refresh_token = await issue_token_pair(db, user.id)
    return access_token, refresh_token, is_new_user
