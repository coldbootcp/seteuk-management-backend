from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AccountPendingDeletionError,
    ConsultationRequiredError,
    EmailNotVerifiedError,
    UserNotFoundError,
)
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


async def get_active_verified_user(user: Annotated[User, Depends(get_current_user)]) -> User:
    """실제 기능(기록 조회·저장, 진단, 챗봇 등)을 쓰려면 이메일 인증을 마쳤고
    탈퇴 유예 중이 아니어야 한다. 두 상태를 스스로 확인하거나 되돌릴 수 있는
    엔드포인트(계정 상태 조회, 인증 메일 재발송, 탈퇴 취소, 로그아웃)는 이
    의존성이 아니라 `get_current_user`를 직접 써서 이 검사에 막히지 않게 한다
    — 그렇지 않으면 막힌 사용자가 스스로 풀 방법이 없어진다."""
    # 소셜 로그인 계정은 제공자가 이미 이메일 소유를 확인했으므로
    # password_hash가 있는 계정(이메일/비밀번호 가입)만 검사한다.
    if user.password_hash is not None and user.email_verified_at is None:
        raise EmailNotVerifiedError("이메일 인증을 먼저 완료해주세요")
    if user.withdrawal_requested_at is not None:
        raise AccountPendingDeletionError(
            "탈퇴가 예약된 계정입니다. 계정 설정에서 탈퇴를 취소해주세요"
        )
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
