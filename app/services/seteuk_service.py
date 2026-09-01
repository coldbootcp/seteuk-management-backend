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
from app.models.user import User
from app.models.volunteer_record import VolunteerRecord
from app.schemas.seteuk import ParseError, SeteukAnalysisResult
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


def _filter_future_grade_data(
    result: SeteukAnalysisResult, current_grade: int | None, current_semester: int | None
) -> SeteukAnalysisResult:
    """학생이 선언한 현재 학년-학기보다 이후 시점의 기록은 반영하지 않는다.

    생기부 문서 자체가 잘못됐거나(다른 사람 것, 미래 버전) 프로필의 현재
    학년-학기를 갱신하지 않은 채 더 최신 생기부를 다시 올린 경우, 아직
    일어나지 않았어야 할 시점의 기록이 파싱돼 진단·로드맵이 "현재 위치"를
    잘못 판단하게 된다. 온보딩 전(current_grade가 아직 없음)이면 비교 기준이
    없으므로 거르지 않는다. Award는 grade/semester가 없고 date만 있어 이
    검사를 적용할 근거가 없다 — 그대로 둔다."""
    if current_grade is None:
        return result

    def _within(grade: int, semester: int | None) -> bool:
        if grade != current_grade:
            return grade < current_grade
        # 같은 학년: semester가 없는 학년 단위 기록(자율활동 등)은 그 학년이
        # 아직 진행 중이어도 이미 부분적으로 있을 수 있으므로 허용한다.
        return semester is None or semester <= (current_semester or 2)

    dropped = 0

    def _filter[T](items: list[T], key) -> list[T]:
        nonlocal dropped
        kept = [item for item in items if _within(*key(item))]
        dropped += len(items) - len(kept)
        return kept

    attendance = _filter(result.attendance, lambda i: (i.grade, None))
    academic_performance = _filter(result.academic_performance, lambda i: (i.grade, i.semester))
    reading_activities = _filter(result.reading_activities, lambda i: (i.grade, i.semester))
    volunteer_records = _filter(result.volunteer_records, lambda i: (i.grade, None))
    activities = _filter(result.activities, lambda i: (i.grade, i.semester))

    errors = list(result.errors)
    if dropped:
        errors.append(
            ParseError(
                block_id="future_grade_filter",
                reason=(
                    f"현재 학년-학기({current_grade}학년"
                    f" {current_semester if current_semester else '?'}학기)보다 이후 시점의"
                    f" 기록 {dropped}건은 반영하지 않았습니다. 학년/학기가 바뀌었다면"
                    " 프로필을 먼저 갱신한 뒤 다시 업로드해주세요."
                ),
            )
        )

    return SeteukAnalysisResult(
        attendance=attendance,
        academic_performance=academic_performance,
        reading_activities=reading_activities,
        awards=result.awards,
        volunteer_records=volunteer_records,
        activities=activities,
        errors=errors,
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
            user = await db.get(User, upload.user_id)
            result = _filter_future_grade_data(
                result,
                user.current_grade if user else None,
                user.current_semester if user else None,
            )
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
