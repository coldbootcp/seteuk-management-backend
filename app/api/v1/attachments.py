import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services import attachment_service

router = APIRouter(prefix="/activities", tags=["attachments"])


class AttachmentRead(BaseModel):
    """본문(content)은 응답에 넣지 않는다 — 목록 한 번에 수 MB가 실린다."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    activity_id: uuid.UUID
    file_name: str
    content_type: str
    size_bytes: int
    # 추출에 실패했거나 PDF가 아니면 빈 문자열이다. 첨부 자체는 성공한다.
    has_extracted_text: bool = False


def _to_read(attachment) -> AttachmentRead:
    return AttachmentRead.model_validate(attachment).model_copy(
        update={"has_extracted_text": bool(attachment.extracted_text)}
    )


@router.post(
    "/{activity_id}/attachments",
    response_model=AttachmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    activity_id: uuid.UUID,
    file: Annotated[UploadFile, File()],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AttachmentRead:
    attachment = await attachment_service.create_attachment(
        db,
        user.id,
        activity_id,
        file_name=file.filename or "attachment",
        content_type=file.content_type,
        content=await file.read(),
    )
    return _to_read(attachment)


@router.get("/{activity_id}/attachments", response_model=list[AttachmentRead])
async def list_attachments(
    activity_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AttachmentRead]:
    rows = await attachment_service.list_attachments(db, user.id, activity_id)
    return [_to_read(row) for row in rows]


@router.get("/attachments/{attachment_id}/file")
async def download_attachment(
    attachment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    attachment = await attachment_service.get_attachment(db, user.id, attachment_id)
    return Response(
        content=attachment.content,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{quote(attachment.file_name)}"'
        },
    )


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    attachment_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await attachment_service.delete_attachment(db, user.id, attachment_id)
