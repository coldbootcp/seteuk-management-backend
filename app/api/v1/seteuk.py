from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.rate_limit import enforce_daily_limit
from app.db.session import get_db
from app.models.usage_event import UsageAction
from app.models.user import User
from app.schemas.seteuk import (
    ImportResultResponse,
    ImportSelectionRequest,
    LatestUploadResponse,
    SeteukAnalysisResult,
    UploadCreateResponse,
    UploadStatusResponse,
)
from app.services import seteuk_service

router = APIRouter(prefix="/seteuk", tags=["seteuk"])


@router.post("/uploads", response_model=UploadCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_upload(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UploadCreateResponse:
    await enforce_daily_limit(db, user.id, UsageAction.SETEUK_UPLOAD)
    file_bytes = await file.read()
    upload = await seteuk_service.create_upload(
        db, user.id, file_bytes, file_name=file.filename, content_type=file.content_type
    )
    background_tasks.add_task(seteuk_service.run_parse_job, upload.id, file_bytes)
    return UploadCreateResponse(upload_id=upload.id, status=upload.status)


@router.get("/uploads/latest", response_model=LatestUploadResponse | None)
async def get_latest_upload(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LatestUploadResponse | None:
    """가장 최근 업로드. 클라이언트가 업로드 id를 들고 있지 않아도 화면이 진행
    상황을 되찾을 수 있어야 한다 — 이 경로가 없으면 파싱 중 새로고침 한 번에
    검토 화면이 사라진다.

    경로가 "/uploads/{upload_id}"보다 먼저 선언돼야 latest가 id로 해석되지 않는다.
    """
    upload = await seteuk_service.get_latest_upload(db, user.id)
    if upload is None:
        return None
    return LatestUploadResponse(
        upload_id=upload.id,
        status=upload.status,
        file_name=upload.file_name,
        parsing_confidence=upload.parsing_confidence,
        imported_at=upload.imported_at,
        failure_reason=upload.failure_reason,
        created_at=upload.created_at,
    )


@router.get("/uploads/{upload_id}", response_model=UploadStatusResponse)
async def get_upload_status(
    upload_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UploadStatusResponse:
    upload = await seteuk_service.get_upload(db, user.id, upload_id)
    return UploadStatusResponse(
        status=upload.status,
        parsing_confidence=upload.parsing_confidence,
        imported_at=upload.imported_at,
    )


@router.get("/uploads/{upload_id}/result", response_model=SeteukAnalysisResult)
async def get_upload_result(
    upload_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SeteukAnalysisResult:
    return await seteuk_service.get_result(db, user.id, upload_id)


@router.get("/uploads/{upload_id}/file")
async def download_upload_file(
    upload_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """업로드한 생기부 원본 내려받기."""
    upload = await seteuk_service.get_upload_file(db, user.id, upload_id)
    file_name = upload.file_name or f"{upload.id}.pdf"
    return Response(
        content=upload.content,
        media_type=upload.content_type or "application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{quote(file_name)}"'},
    )


@router.post("/uploads/{upload_id}/import", response_model=ImportResultResponse)
async def import_upload(
    upload_id: UUID,
    data: ImportSelectionRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ImportResultResponse:
    """검토를 마친 파싱 결과 중 학생이 고른 것만 기록에 반영한다.

    파싱과 반영을 나눈 이유는, 파서가 잘못 읽은 항목이나 이제 와서 넣고 싶지 않은
    활동을 그대로 밀어 넣지 않기 위해서다. 영역을 생략하면 그 영역 전체가 반영된다.
    """
    payload = data.model_dump()
    # 요청은 목록으로 오고 서비스는 (영역, index)로 찾는다 — 여기서 옮긴다.
    payload["period_overrides"] = {
        (o.section, o.index): (o.grade, o.semester) for o in data.period_overrides
    }
    imported = await seteuk_service.import_result(
        db, user.id, upload_id, seteuk_service.ImportSelection(**payload)
    )
    return ImportResultResponse(imported=imported)
