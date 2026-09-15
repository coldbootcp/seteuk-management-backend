import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.exceptions import InvalidTokenError

settings = get_settings()

# 최소 8자 이상, 영문/숫자 각 1개 이상. 특수문자를 강제하지 않는 이유는 NIST
# SP 800-63B가 복잡성 규칙보다 길이를 우선하라고 권고하기 때문 — 지나친 규칙은
# 사용자가 예측 가능한 패턴("Password1!")으로 우회하게 만든다.
MIN_PASSWORD_LENGTH = 8


def validate_password_strength(password: str) -> str | None:
    """문제가 있으면 사용자에게 보여줄 한국어 메시지를, 없으면 None을 돌려준다."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"비밀번호는 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다"
    if not any(char.isalpha() for char in password):
        return "비밀번호에 영문자를 포함해주세요"
    if not any(char.isdigit() for char in password):
        return "비밀번호에 숫자를 포함해주세요"
    return None


def generate_opaque_token() -> tuple[str, str]:
    """(원문, 해시) 쌍을 돌려준다. 원문은 이메일로만 나가고 DB에는 해시만
    남긴다 — DB가 유출돼도 토큰을 재현할 수 없게 하기 위함(OWASP Forgot
    Password Cheat Sheet)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_opaque_token(raw)


def hash_opaque_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


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
