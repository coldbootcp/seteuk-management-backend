from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConsultationRequiredError, UserNotFoundError
from app.core.security import TokenType, decode_token
from app.db.session import get_db
from app.models.user import User
from app.services import consultation_service

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    user_id = decode_token(credentials.credentials, TokenType.ACCESS)

    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise UserNotFoundError("사용자를 찾을 수 없습니다")

    return user


async def require_consultation_satisfied(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """진단+상담 관문. 프로필이 아직 없으면(온보딩 전) 이 의존성의 관심사가
    아니므로 통과시킨다 — 현재 학년-학기에 대해 완료(concluded)된 상담이
    없으면 막는다. has_completed_diagnosis_before와 같은 '존재 조회' 방식이라
    User에 별도 boolean 플래그를 두지 않는다."""
    if user.current_grade is None or user.current_semester is None:
        return user

    status = await consultation_service.get_status(db, user)
    if not status.satisfied:
        raise ConsultationRequiredError(
            "진단과 상담을 먼저 마쳐야 합니다",
            extra={
                "required_kind": status.required_kind,
                "target_grade": status.target_grade,
                "target_semester": status.target_semester,
                "resumable_session_id": (
                    str(status.resumable_session_id) if status.resumable_session_id else None
                ),
            },
        )
    return user
