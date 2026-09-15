from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import InvalidCredentialsError
from app.core.security import verify_password
from app.models.user import User
from app.schemas.account import AccountStatusResponse
from app.services import auth_service


def _to_status(user: User) -> AccountStatusResponse:
    settings = get_settings()
    scheduled_deletion_at = (
        user.withdrawal_requested_at
        + timedelta(days=settings.account_deletion_grace_days)
        if user.withdrawal_requested_at
        else None
    )
    return AccountStatusResponse(
        email=user.email,
        email_verified=user.email_verified_at is not None,
        has_password=user.password_hash is not None,
        google_linked=user.google_id is not None,
        kakao_linked=user.kakao_id is not None,
        withdrawal_requested_at=user.withdrawal_requested_at,
        scheduled_deletion_at=scheduled_deletion_at,
    )


def get_status(user: User) -> AccountStatusResponse:
    return _to_status(user)


async def withdraw(db: AsyncSession, user: User, password: str | None) -> AccountStatusResponse:
    """세션 탈취만으로 탈퇴가 되지 않도록, 비밀번호 계정은 비밀번호 재확인을
    요구한다. 소셜 전용 계정(비밀번호 없음)은 생략한다."""
    if user.password_hash is not None:
        if not password or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError("비밀번호가 올바르지 않습니다")

    await auth_service.request_withdrawal(db, user)
    return _to_status(user)


async def cancel_withdrawal(db: AsyncSession, user: User) -> AccountStatusResponse:
    await auth_service.cancel_withdrawal(db, user)
    return _to_status(user)
