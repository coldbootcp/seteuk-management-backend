import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_active_verified_user, get_current_user
from app.core.rate_limit import enforce_daily_limit
from app.db.session import get_db
from app.models.consultation import ConsultationSession, ConsultationStatus
from app.models.usage_event import UsageAction
from app.models.user import User
from app.schemas.consultation import (
    ConfirmFullReplanRequest,
    ConsultationMessageCreate,
    ConsultationSessionRead,
    ConsultationStatusResponse,
)
from app.services import chat_service, consultation_service

# 관문(require_consultation_satisfied)을 걸지 않는다 — 여기가 관문을 풀기 위한
# 경로이기 때문이다.
router = APIRouter(prefix="/consultation", tags=["consultation"])


def _to_read(session: ConsultationSession) -> ConsultationSessionRead:
    return ConsultationSessionRead(
        id=session.id,
        conversation_id=session.conversation_id,
        kind=session.kind,
        target_grade=session.target_grade,
        target_semester=session.target_semester,
        status=session.status,
        ready=session.status == ConsultationStatus.READY.value,
        full_replan_confirmed=session.full_replan_confirmed_at is not None,
    )


@router.get("/status", response_model=ConsultationStatusResponse)
async def get_status(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConsultationStatusResponse:
    return await consultation_service.get_status(db, user)


@router.post("/sessions", response_model=ConsultationSessionRead)
async def create_or_resume_session(
    user: Annotated[User, Depends(get_active_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConsultationSessionRead:
    session = await consultation_service.get_or_create_session(db, user)
    return _to_read(session)


@router.get("/sessions/{session_id}", response_model=ConsultationSessionRead)
async def get_session(
    session_id: uuid.UUID,
    user: Annotated[User, Depends(get_active_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConsultationSessionRead:
    session = await consultation_service.get_session(db, user.id, session_id)
    return _to_read(session)


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: uuid.UUID,
    data: ConsultationMessageCreate,
    user: Annotated[User, Depends(get_active_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    await consultation_service.get_session(db, user.id, session_id)
    await enforce_daily_limit(db, user.id, UsageAction.CHAT_MESSAGE)
    return StreamingResponse(
        chat_service.stream_consultation_reply(user.id, session_id, data.content),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/sessions/{session_id}/confirm-full-replan", response_model=ConsultationSessionRead)
async def confirm_full_replan(
    session_id: uuid.UUID,
    data: ConfirmFullReplanRequest,
    user: Annotated[User, Depends(get_active_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConsultationSessionRead:
    session = await consultation_service.confirm_full_replan(
        db, user.id, session_id, data.confirmed
    )
    return _to_read(session)


@router.post("/sessions/{session_id}/conclude", response_model=ConsultationSessionRead)
async def conclude_session(
    session_id: uuid.UUID,
    user: Annotated[User, Depends(get_active_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConsultationSessionRead:
    session = await consultation_service.get_session(db, user.id, session_id)
    session = await consultation_service.conclude(db, user, session)
    return _to_read(session)
