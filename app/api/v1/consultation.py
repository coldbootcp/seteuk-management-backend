import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_active_verified_user, get_current_user
from app.core.rate_limit import enforce_daily_limit
from app.db.session import get_db
from app.models.consultation import ConsultationKind, ConsultationSession, ConsultationStatus
from app.models.usage_event import UsageAction
from app.models.user import User
from app.schemas.chat import MessageRead
from app.schemas.consultation import (
    ConfirmFlowRequest,
    ConfirmFullReplanRequest,
    ConsultationMessageCreate,
    ConsultationSessionRead,
    ConsultationStatusResponse,
)
from app.services import chat_service, consultation_service, record_review_consultation
from app.services.consultation_stage import session_stage

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
        stage=session_stage(session),
        flow=session.draft_flow,
        flow_confirmed=session.flow_confirmed_at is not None,
        semester_goal=session.semester_goal,
    )


async def _read(db: AsyncSession, session: ConsultationSession) -> ConsultationSessionRead:
    """_to_read에 생기부 확인 상담의 현황(DB 조회가 필요)을 덧붙인다."""
    read = _to_read(session)
    if session.kind == ConsultationKind.RECORD_REVIEW.value:
        read.record_review = await record_review_consultation.state(db, session)
    return read


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
    return await _read(db, session)


@router.get("/sessions/{session_id}/messages", response_model=list[MessageRead])
async def list_session_messages(
    session_id: uuid.UUID,
    user: Annotated[User, Depends(get_active_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[MessageRead]:
    """세션에 오간 대화를 시간순으로 돌려준다. 화면이 상담을 다시 열 때 이 기록으로
    이전 대화를 복원하고, 비어 있으면 첫 인사(opening)를 새로 요청한다."""
    session = await consultation_service.get_session(db, user.id, session_id)
    messages = await chat_service.list_messages(db, user.id, session.conversation_id)
    return [MessageRead.model_validate(m) for m in messages]


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


@router.post("/sessions/{session_id}/opening")
async def send_opening(
    session_id: uuid.UUID,
    user: Annotated[User, Depends(get_active_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """새로 열린 세션의 첫 인사를 챗봇이 먼저 건네게 한다. 화면은 세션에 메시지가
    하나도 없을 때만 부른다(이미 대화가 있으면 서비스가 조용히 넘긴다)."""
    await consultation_service.get_session(db, user.id, session_id)
    return StreamingResponse(
        chat_service.stream_consultation_opening(user.id, session_id),
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


@router.post("/sessions/{session_id}/confirm-flow", response_model=ConsultationSessionRead)
async def confirm_flow(
    session_id: uuid.UUID,
    data: ConfirmFlowRequest,
    user: Annotated[User, Depends(get_active_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConsultationSessionRead:
    """상담 화면의 3개년 흐름 카드에서 학생이 '이 흐름으로 확정'(또는 '다시 조율')을
    눌렀을 때. 흐름이 확정돼야 챗봇이 이번 학기 목표로 넘어갈 수 있다."""
    session = await consultation_service.confirm_flow(db, user.id, session_id, data.confirmed)
    return _to_read(session)


@router.post("/sessions/{session_id}/conclude", response_model=ConsultationSessionRead)
async def conclude_session(
    session_id: uuid.UUID,
    user: Annotated[User, Depends(get_active_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConsultationSessionRead:
    session = await consultation_service.get_session(db, user.id, session_id)
    if session.kind == ConsultationKind.RECORD_REVIEW.value:
        # 생기부 확인 상담은 로드맵이 아니라 생기부를 반영한다(정한 범위·충돌 선택대로).
        await record_review_consultation.conclude(db, user, session)
        return await _read(db, session)
    session = await consultation_service.conclude(db, user, session)
    return _to_read(session)


@router.post("/record-review", response_model=ConsultationSessionRead)
async def create_or_resume_record_review(
    user: Annotated[User, Depends(get_active_verified_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConsultationSessionRead:
    """확인을 기다리는 교체 업로드(설정 탭 생기부 올리기)의 확인 상담을 열거나 이어 간다.
    확인할 생기부가 없으면 409(CONSULTATION_NOT_READY)."""
    session = await record_review_consultation.get_or_create_session(db, user)
    return await _read(db, session)
