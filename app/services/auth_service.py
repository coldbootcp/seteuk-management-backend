from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EmailAlreadyExistsError, InvalidCredentialsError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import LoginRequest, SignupRequest


async def signup(db: AsyncSession, data: SignupRequest) -> tuple[User, str, str]:
    existing = await db.scalar(select(User).where(User.email == data.email))
    if existing is not None:
        raise EmailAlreadyExistsError("이미 가입된 이메일입니다")

    user = User(email=data.email, password_hash=hash_password(data.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return user, create_access_token(user.id), create_refresh_token(user.id)


async def login(db: AsyncSession, data: LoginRequest) -> tuple[str, str]:
    user = await db.scalar(select(User).where(User.email == data.email))
    if user is None or user.password_hash is None:
        raise InvalidCredentialsError("이메일 또는 비밀번호가 올바르지 않습니다")

    if not verify_password(data.password, user.password_hash):
        raise InvalidCredentialsError("이메일 또는 비밀번호가 올바르지 않습니다")

    return create_access_token(user.id), create_refresh_token(user.id)
