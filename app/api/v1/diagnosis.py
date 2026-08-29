from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.rate_limit import enforce_daily_limit
from app.db.session import get_db
from app.models.usage_event import UsageAction
from app.models.user import User
from app.schemas.diagnosis import (
    DiagnosisCreateResponse,
    DiagnosisResult,
    PreQuestionAnswersRequest,
    PreQuestionsResponse,
)
from app.services import diagnosis_service

router = APIRouter(prefix="/diagnosis", tags=["diagnosis"])


@router.get("/pre-questions", response_model=PreQuestionsResponse)
async def get_pre_questions(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PreQuestionsResponse:
    questions = await diagnosis_service.get_pre_questions(db, user.id)
    return PreQuestionsResponse(questions=questions)


@router.post("/pre-questions/answers", status_code=status.HTTP_204_NO_CONTENT)
async def submit_pre_question_answers(
    data: PreQuestionAnswersRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await diagnosis_service.submit_pre_question_answers(db, user.id, data.answers)


@router.post("", response_model=DiagnosisCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_diagnosis(
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DiagnosisCreateResponse:
    await enforce_daily_limit(db, user.id, UsageAction.DIAGNOSIS)
    diagnosis = await diagnosis_service.create_diagnosis(db, user.id)
    background_tasks.add_task(diagnosis_service.run_diagnosis_job, diagnosis.id, user.id)
    return DiagnosisCreateResponse(diagnosis_id=diagnosis.id, status=diagnosis.status)


@router.get("/latest", response_model=DiagnosisResult)
async def get_latest_diagnosis(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DiagnosisResult:
    diagnosis = await diagnosis_service.get_latest_diagnosis(db, user.id)
    return diagnosis_service.to_result(diagnosis)


@router.get("/{diagnosis_id}", response_model=DiagnosisResult)
async def get_diagnosis(
    diagnosis_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DiagnosisResult:
    diagnosis = await diagnosis_service.get_diagnosis(db, user.id, diagnosis_id)
    return diagnosis_service.to_result(diagnosis)
