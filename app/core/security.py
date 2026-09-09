from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.exceptions import InvalidTokenError

settings = get_settings()


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def _create_token(
    user_id: UUID, token_type: TokenType, expires_delta: timedelta, jti: UUID | None = None
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": token_type.value,
        "iat": now,
        "exp": now + expires_delta,
    }
    if jti is not None:
        payload["jti"] = str(jti)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: UUID) -> str:
    return _create_token(
        user_id, TokenType.ACCESS, timedelta(minutes=settings.access_token_expire_minutes)
    )


def refresh_token_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)


def create_refresh_token(user_id: UUID, jti: UUID) -> str:
    """jti는 refresh_tokens 테이블의 행 id다 — 이 값이 있어야 로그아웃으로
    개별 토큰을 무효화할 수 있다."""
    return _create_token(
        user_id, TokenType.REFRESH, timedelta(days=settings.refresh_token_expire_days), jti=jti
    )


def decode_token(token: str, expected_type: TokenType) -> UUID:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise InvalidTokenError("유효하지 않은 토큰입니다") from exc

    if payload.get("type") != expected_type.value:
        raise InvalidTokenError("토큰 타입이 올바르지 않습니다")

    try:
        return UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError("토큰 페이로드가 올바르지 않습니다") from exc


def decode_refresh_token(token: str) -> tuple[UUID, UUID]:
    """(user_id, jti)를 돌려준다. jti가 없는 토큰은 이 테이블 도입 이전에 발급된
    것이므로 더 이상 받지 않는다."""
    user_id = decode_token(token, TokenType.REFRESH)
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    try:
        return user_id, UUID(payload["jti"])
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError("다시 로그인해주세요") from exc
