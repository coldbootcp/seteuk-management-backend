import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnsupportedFileError, UploadNotFoundError, UploadNotReadyError
from app.db.session import AsyncSessionLocal
from app.models.academic_performance import AcademicPerformance
from app.models.activity import Activity
from app.models.attendance import Attendance
from app.models.award import Award
from app.models.reading_activity import ReadingActivity
from app.models.seteuk_upload import SeteukUpload, UploadStatus
from app.models.volunteer_record import VolunteerRecord
from app.schemas.seteuk import SeteukAnalysisResult
from app.services.parser.pipeline import parse_seteuk_pdf


async def create_upload(db: AsyncSession, user_id: uuid.UUID, file_bytes: bytes) -> SeteukUpload:
    if not file_bytes.startswith(b"%PDF"):
        raise UnsupportedFileError("텍스트 PDF만 지원합니다")

    upload = SeteukUpload(user_id=user_id, status=UploadStatus.PROCESSING.value)
    db.add(upload)
    await db.commit()
    await db.refresh(upload)
    return upload


_SETEUK_DOMAIN_MODELS = (
    Attendance,
    AcademicPerformance,
    ReadingActivity,
    Award,
    VolunteerRecord,
    Activity,
)


async def _replace_previous_upload_data(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Deletes only rows that trace back to an earlier 생기부 upload for this user.
    Rows with source_upload_id=NULL were entered some other way (e.g. a future manual
    edit) and are left untouched — a re-upload replaces the parser's own data, not
    anything the user added themselves."""
    for model in _SETEUK_DOMAIN_MODELS:
        await db.execute(
            delete(model).where(model.user_id == user_id, model.source_upload_id.is_not(None))
        )


def _persist_result(
    db: AsyncSession, user_id: uuid.UUID, upload_id: uuid.UUID, result: SeteukAnalysisResult
) -> None:
    for item in result.attendance:
        db.add(Attendance(user_id=user_id, source_upload_id=upload_id, **item.model_dump()))
    for item in result.academic_performance:
        db.add(
            AcademicPerformance(user_id=user_id, source_upload_id=upload_id, **item.model_dump())
        )
    for item in result.reading_activities:
        db.add(ReadingActivity(user_id=user_id, source_upload_id=upload_id, **item.model_dump()))
    for item in result.awards:
        db.add(Award(user_id=user_id, source_upload_id=upload_id, **item.model_dump()))
    for item in result.volunteer_records:
        db.add(VolunteerRecord(user_id=user_id, source_upload_id=upload_id, **item.model_dump()))
    for item in result.activities:
        db.add(Activity(user_id=user_id, source_upload_id=upload_id, **item.model_dump()))


async def run_parse_job(upload_id: uuid.UUID, pdf_bytes: bytes) -> None:
    """Parses the PDF (kept only in memory — never written to disk) and, on success,
    replaces this user's previous upload-sourced rows with the new result in the same
    job. There is no separate confirm/apply step: a "done" status means the data is
    already in place."""
    async with AsyncSessionLocal() as db:
        upload = await db.get(SeteukUpload, upload_id)
        if upload is None:
            return

        try:
            result = await parse_seteuk_pdf(pdf_bytes)
            upload.raw_result = result.model_dump(mode="json")
            await _replace_previous_upload_data(db, upload.user_id)
            _persist_result(db, upload.user_id, upload.id, result)
            upload.status = UploadStatus.DONE.value
        except Exception as exc:
            upload.status = UploadStatus.FAILED.value
            upload.failure_reason = f"{type(exc).__name__}: {exc}"

        await db.commit()


async def get_upload(db: AsyncSession, user_id: uuid.UUID, upload_id: uuid.UUID) -> SeteukUpload:
    upload = await db.scalar(
        select(SeteukUpload).where(SeteukUpload.id == upload_id, SeteukUpload.user_id == user_id)
    )
    if upload is None:
        raise UploadNotFoundError("업로드를 찾을 수 없습니다")
    return upload


async def get_result(
    db: AsyncSession, user_id: uuid.UUID, upload_id: uuid.UUID
) -> SeteukAnalysisResult:
    upload = await get_upload(db, user_id, upload_id)
    if upload.status != UploadStatus.DONE.value or upload.raw_result is None:
        raise UploadNotReadyError("파싱이 완료되지 않았습니다")
    return SeteukAnalysisResult.model_validate(upload.raw_result)
