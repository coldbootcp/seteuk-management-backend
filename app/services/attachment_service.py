"""활동 첨부파일 — 수행평가 안내문, 보고서 등.

통합 결정 P-1에 따라 파일 본문을 PostgreSQL에 담는다. 프론트엔드 프로토타입은 R2에
올리고 키만 들고 있었지만 Workers를 버리면서 저장소도 하나로 모았다.

`extracted_text`만 LLM 컨텍스트에 실린다 — 본문(`content`)은 절대 싣지 않는다.
"""

import io
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import RecordNotFoundError, UnsupportedFileError
from app.models.activity import Activity
from app.models.activity_attachment import ActivityAttachment
from app.services.record_service import get_record

# 학생이 올리는 안내문·보고서 기준. 생기부(50MB)보다 훨씬 작아도 충분하다.
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


def _extract_text(content: bytes, content_type: str | None) -> str:
    """검색과 LLM 입력에 쓸 본문 텍스트. 추출에 실패해도 첨부 자체는 성공시킨다 —
    파일을 붙여 두는 것과 그 안을 읽는 것은 별개의 기능이다."""
    if not (content_type or "").startswith("application/pdf") and not content.startswith(b"%PDF"):
        return ""
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages).strip()
    except Exception:
        return ""


async def create_attachment(
    db: AsyncSession,
    user_id: uuid.UUID,
    activity_id: uuid.UUID,
    *,
    file_name: str,
    content_type: str | None,
    content: bytes,
) -> ActivityAttachment:
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise UnsupportedFileError("첨부파일은 10MB까지 올릴 수 있습니다")

    # 소유권은 활동을 통해 확인한다 — 남의 활동에 파일을 붙일 수 없다.
    await get_record(db, Activity, user_id, activity_id)

    attachment = ActivityAttachment(
        user_id=user_id,
        activity_id=activity_id,
        file_name=file_name,
        content_type=content_type or "application/octet-stream",
        size_bytes=len(content),
        content=content,
        extracted_text=_extract_text(content, content_type),
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)
    return attachment


async def list_attachments(
    db: AsyncSession, user_id: uuid.UUID, activity_id: uuid.UUID
) -> list[ActivityAttachment]:
    rows = await db.scalars(
        select(ActivityAttachment)
        .where(
            ActivityAttachment.user_id == user_id,
            ActivityAttachment.activity_id == activity_id,
        )
        .order_by(ActivityAttachment.created_at.asc())
    )
    return list(rows)


async def get_attachment(
    db: AsyncSession, user_id: uuid.UUID, attachment_id: uuid.UUID
) -> ActivityAttachment:
    attachment = await db.scalar(
        select(ActivityAttachment).where(
            ActivityAttachment.id == attachment_id,
            ActivityAttachment.user_id == user_id,
        )
    )
    if attachment is None:
        raise RecordNotFoundError("첨부파일을 찾을 수 없습니다")
    return attachment


async def delete_attachment(
    db: AsyncSession, user_id: uuid.UUID, attachment_id: uuid.UUID
) -> None:
    attachment = await get_attachment(db, user_id, attachment_id)
    await db.delete(attachment)
    await db.commit()
