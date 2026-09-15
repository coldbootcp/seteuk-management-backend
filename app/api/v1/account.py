from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.account import AccountStatusResponse, WithdrawAccountRequest
from app.services import account_service

# 여기는 일부러 get_active_verified_user를 쓰지 않는다 — 이메일 인증이 안
# 끝났거나 탈퇴가 예약된 계정도 "내 상태가 뭔지" 확인하고 "탈퇴를 취소"할 수
# 있어야 하는데, 그 관문 자체로 막으면 스스로 풀 방법이 없어진다
# (consultation.py의 get_status와 같은 이유).
router = APIRouter(prefix="/account", tags=["account"])


@router.get("/status", response_model=AccountStatusResponse)
async def get_status(user: Annotated[User, Depends(get_current_user)]) -> AccountStatusResponse:
    return account_service.get_status(user)


@router.post("/withdraw", response_model=AccountStatusResponse)
async def withdraw(
    data: WithdrawAccountRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AccountStatusResponse:
    return await account_service.withdraw(db, user, data.password)


@router.post("/cancel-withdrawal", response_model=AccountStatusResponse)
async def cancel_withdrawal(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AccountStatusResponse:
    return await account_service.cancel_withdrawal(db, user)
