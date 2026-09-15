import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    InvalidResetTokenError,
    InvalidTokenError,
    InvalidVerificationTokenError,
    SocialAuthError,
    WeakPasswordError,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    refresh_token_expiry,
    validate_password_strength,
    verify_password,
)
from app.models.email_verification_token import EmailVerificationToken
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import LoginRequest, SignupRequest
from app.services import email_service

settings = get_settings()

KAKAO_USER_INFO_URL = "https://kapi.kakao.com/v2/user/me"
KAKAO_TIMEOUT_SECONDS = 10

GOOGLE_USER_INFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_TIMEOUT_SECONDS = 10


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

    await _issue_and_send_verification_email(db, user)

    access_token, refresh_token = await issue_token_pair(db, user.id)
    return user, access_token, refresh_token


async def login(db: AsyncSession, data: LoginRequest) -> tuple[str, str]:
    user = await db.scalar(select(User).where(User.email == data.email))
    if user is None or user.password_hash is None:
        raise InvalidCredentialsError("이메일 또는 비밀번호가 올바르지 않습니다")

    if not verify_password(data.password, user.password_hash):
        raise InvalidCredentialsError("이메일 또는 비밀번호가 올바르지 않습니다")

    return await issue_token_pair(db, user.id)


async def _issue_and_send_verification_email(db: AsyncSession, user: User) -> None:
    raw, token_hash = generate_opaque_token()
    db.add(
        EmailVerificationToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC)
            + timedelta(hours=settings.email_verification_token_expire_hours),
        )
    )
    await db.commit()
    await email_service.send_verification_email(user.email, raw)


async def resend_verification_email(db: AsyncSession, email: str) -> None:
    """이메일 존재 여부를 노출하지 않기 위해 호출부는 항상 같은 응답을 준다 —
    여기서는 실제로 보낼지만 결정한다."""
    user = await db.scalar(select(User).where(User.email == email))
    if user is None or user.password_hash is None or user.email_verified_at is not None:
        return
    await _issue_and_send_verification_email(db, user)


async def verify_email(db: AsyncSession, raw_token: str) -> None:
    token_hash = hash_opaque_token(raw_token)
    entry = await db.scalar(
        select(EmailVerificationToken).where(EmailVerificationToken.token_hash == token_hash)
    )
    if (
        entry is None
        or entry.used_at is not None
        or entry.expires_at < datetime.now(UTC)
    ):
        raise InvalidVerificationTokenError(
            "인증 링크가 만료되었거나 이미 사용되었습니다. 다시 요청해주세요"
        )

    user = await db.get(User, entry.user_id)
    if user is None:
        raise InvalidVerificationTokenError("계정을 찾을 수 없습니다")

    entry.used_at = datetime.now(UTC)
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
    await db.commit()


async def request_password_reset(db: AsyncSession, email: str) -> None:
    """이메일 존재 여부를 노출하지 않기 위해 호출부는 항상 같은 응답을 준다."""
    user = await db.scalar(select(User).where(User.email == email))
    if user is None or user.password_hash is None:
        return

    raw, token_hash = generate_opaque_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC)
            + timedelta(minutes=settings.password_reset_token_expire_minutes),
        )
    )
    await db.commit()
    await email_service.send_password_reset_email(user.email, raw)


async def reset_password(db: AsyncSession, raw_token: str, new_password: str) -> None:
    error = validate_password_strength(new_password)
    if error:
        raise WeakPasswordError(error)

    token_hash = hash_opaque_token(raw_token)
    entry = await db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    if (
        entry is None
        or entry.used_at is not None
        or entry.expires_at < datetime.now(UTC)
    ):
        raise InvalidResetTokenError(
            "재설정 링크가 만료되었거나 이미 사용되었습니다. 다시 요청해주세요"
        )

    user = await db.get(User, entry.user_id)
    if user is None:
        raise InvalidResetTokenError("계정을 찾을 수 없습니다")

    entry.used_at = datetime.now(UTC)
    user.password_hash = hash_password(new_password)
    # 비밀번호가 새어서 재설정하는 경우일 수 있으므로, 다른 모든 기기의 세션도
    # 함께 끊는다(OWASP: 인증 요소 변경 후 다른 세션 종료 옵션 제공).
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()


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

    # 카카오가 이미 이 이메일의 소유를 확인해 준 것이므로, 아직 이메일 인증을
    # 안 마친 비밀번호 계정에 연결되는 경우라도 여기서 함께 인증 처리한다.
    if email and user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(user)

    access_token, refresh_token = await issue_token_pair(db, user.id)
    return access_token, refresh_token, is_new_user


async def _fetch_google_profile(google_access_token: str) -> tuple[str, str | None]:
    """카카오와 같은 패턴 — 프론트엔드는 Google Identity Services의 OAuth2 토큰
    클라이언트로 access token만 받아 넘기고, 백엔드가 그 토큰으로 구글
    userinfo 엔드포인트를 직접 불러 신원을 확인한다. 클라이언트가 보낸 사용자
    정보를 그대로 믿지 않는다."""
    async with httpx.AsyncClient(timeout=GOOGLE_TIMEOUT_SECONDS) as client:
        try:
            response = await client.get(
                GOOGLE_USER_INFO_URL,
                headers={"Authorization": f"Bearer {google_access_token}"},
            )
        except httpx.HTTPError as exc:
            raise SocialAuthError(f"구글 서버에 연결하지 못했습니다: {exc}") from exc

    if response.status_code != 200:
        raise SocialAuthError("구글 토큰이 유효하지 않습니다")

    payload = response.json()
    google_id = payload.get("sub")
    if google_id is None:
        raise SocialAuthError("구글 응답에서 사용자 식별자를 찾지 못했습니다")

    return str(google_id), payload.get("email")


async def google_login(db: AsyncSession, google_access_token: str) -> tuple[str, str, bool]:
    google_id, email = await _fetch_google_profile(google_access_token)

    user = await db.scalar(select(User).where(User.google_id == google_id))
    is_new_user = False

    if user is None and email:
        # 같은 이메일로 이미 가입해 둔 계정이 있으면 새로 만들지 않고 연결한다.
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            user.google_id = google_id

    if user is None:
        if not email:
            raise SocialAuthError("구글 계정에서 이메일 정보를 가져오지 못했습니다")
        user = User(email=email, google_id=google_id)
        db.add(user)
        is_new_user = True

    # 구글이 이미 이메일 소유를 확인했으므로(email_verified 클레임과 무관하게
    # 구글 계정으로 로그인했다는 사실 자체가 증거다) 인증을 함께 마친다.
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(user)

    access_token, refresh_token = await issue_token_pair(db, user.id)
    return access_token, refresh_token, is_new_user


async def request_withdrawal(db: AsyncSession, user: User) -> datetime:
    """탈퇴를 즉시 확정하지 않고 유예 기간을 둔다 — 배치 삭제는
    maintenance_service.purge_withdrawn_accounts가 맡는다. 다른 기기의
    세션도 모두 끊어 탈퇴 의사가 확정된 뒤 계정이 계속 쓰이지 않게 한다."""
    if user.withdrawal_requested_at is None:
        user.withdrawal_requested_at = datetime.now(UTC)
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await db.commit()
    return user.withdrawal_requested_at


async def cancel_withdrawal(db: AsyncSession, user: User) -> None:
    if user.withdrawal_requested_at is not None:
        user.withdrawal_requested_at = None
        await db.commit()


async def purge_withdrawn_accounts(db: AsyncSession, grace_days: int) -> int:
    """유예 기간이 지난 탈퇴 계정을 완전히 삭제한다. users.id를 참조하는 모든
    테이블이 ON DELETE CASCADE라(auth hardening 마이그레이션), 사용자 행 하나만
    지우면 활동·성적·대화 등 전 도메인 데이터가 DB 레벨에서 함께 지워진다."""
    cutoff = datetime.now(UTC) - timedelta(days=grace_days)
    result = await db.execute(
        delete(User).where(
            User.withdrawal_requested_at.is_not(None), User.withdrawal_requested_at < cutoff
        )
    )
    await db.commit()
    return result.rowcount or 0
