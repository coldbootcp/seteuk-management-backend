from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.seteuk import SeteukAnalysisResult, UploadCreateResponse, UploadStatusResponse
from app.services import seteuk_service

router = APIRouter(prefix="/seteuk", tags=["seteuk"])


@router.post("/uploads", response_model=UploadCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_upload(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UploadCreateResponse:
    file_bytes = await file.read()
    upload = await seteuk_service.create_upload(db, user.id, file_bytes)
    background_tasks.add_task(seteuk_service.run_parse_job, upload.id, file_bytes)
    return UploadCreateResponse(upload_id=upload.id, status=upload.status)


@router.get("/uploads/{upload_id}", response_model=UploadStatusResponse)
async def get_upload_status(
    upload_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UploadStatusResponse:
    upload = await seteuk_service.get_upload(db, user.id, upload_id)
    return UploadStatusResponse(status=upload.status, parsing_confidence=upload.parsing_confidence)


@router.get("/uploads/{upload_id}/result", response_model=SeteukAnalysisResult)
async def get_upload_result(
    upload_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SeteukAnalysisResult:
    return await seteuk_service.get_result(db, user.id, upload_id)
