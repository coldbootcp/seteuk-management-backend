"""활동 첨부파일 — 수행평가 안내문, 보고서 등.

통합 결정 P-1에 따라 파일 본문을 PostgreSQL에 담는다. 프론트엔드 프로토타입은 R2에
올리고 키만 들고 있었지만 Workers를 버리면서 저장소도 하나로 모았다.

`extracted_text`만 LLM 컨텍스트에 실린다 — 본문(`content`)은 절대 싣지 않는다.
"""

import io
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.core.exceptions import RecordNotFoundError, UnsupportedFileError
from app.models.activity import Activity
from app.models.activity_attachment import ActivityAttachment
from app.services.record_service import get_record

# 학생이 올리는 안내문·보고서 기준. 생기부(50MB)보다 훨씬 작아도 충분하다.
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

# 허용 형식은 발표자료·탐구보고서 기준으로 PDF·DOCX·PPTX만. 화면(accept 속성)이
# 이미 이 셋으로 제한하지만, API를 직접 부르면 어떤 파일이든 저장되던 문제가
# 있었다(방어 심층). 확장자·선언된 MIME·실제 매직바이트를 함께 본다 — 확장자나
# content_type은 위조할 수 있으므로 바이트 시그니처가 최종 근거다.
_UNSUPPORTED_FILE_MESSAGE = (
    "PDF, DOCX, PPTX 파일만 올릴 수 있습니다. "
    "발표자료·탐구보고서를 이 형식으로 저장해 첨부해주세요."
)
_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx"}
_ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    # 일부 클라이언트는 office 파일을 일반 zip으로 신고한다 — 확장자·매직으로 다시 건다.
    "application/zip",
    "application/octet-stream",
}


def _looks_like_allowed_file(file_name: str, content: bytes) -> bool:
    """확장자와 매직바이트가 모두 허용 형식과 맞는지 본다.

    PDF는 '%PDF'로 시작하고, DOCX·PPTX는 OOXML(=ZIP) 컨테이너라 'PK\\x03\\x04'로
    시작한다. 둘 다 앞 4바이트만 봐도 충분하다.
    """
    lowered = file_name.lower()
    extension = lowered[lowered.rfind(".") :] if "." in lowered else ""
    if extension not in _ALLOWED_EXTENSIONS:
        return False
    if extension == ".pdf":
        return content.startswith(b"%PDF")
    # .docx / .pptx
    return content.startswith(b"PK\x03\x04")


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

    # 형식 검증: 확장자·매직바이트가 허용 형식(PDF·DOCX·PPTX)과 맞아야 한다. 선언된
    # content_type도 함께 보되, 위조 가능하므로 매직바이트 검사가 최종 근거다.
    if not _looks_like_allowed_file(file_name, content) or (
        content_type and content_type not in _ALLOWED_CONTENT_TYPES
    ):
        raise UnsupportedFileError(_UNSUPPORTED_FILE_MESSAGE)

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


async def list_all_attachments(db: AsyncSession, user_id: uuid.UUID) -> list[ActivityAttachment]:
    """학생의 첨부파일 전부(본문 제외). 작업공간을 열 때 활동마다 따로 묻던 것을 한 번으로
    줄인다 — 활동이 100건을 넘는 학생은 요청 100여 개가 한꺼번에 몰려 DB 연결을 다 잡아
    먹고 운영에서 30초씩 걸렸다. 파일 본문(content)은 목록에 필요 없어 읽지 않는다."""
    rows = await db.scalars(
        select(ActivityAttachment)
        .options(defer(ActivityAttachment.content))
        .where(ActivityAttachment.user_id == user_id)
        .order_by(ActivityAttachment.created_at.asc())
    )
    return list(rows)


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
