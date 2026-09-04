import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

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


async def create_upload(
    db: AsyncSession,
    user_id: uuid.UUID,
    file_bytes: bytes,
    file_name: str | None = None,
    content_type: str | None = None,
) -> SeteukUpload:
    """업로드 원본을 계정에 보관한다(통합 결정 P-1). 예전 방침은 "PDF 원본은 저장하지
    않는다"였지만, 학생이 나중에 자기가 올린 파일을 다시 확인할 수 있어야 한다는
    판단으로 뒤집었다. 원본은 파싱 결과와 달리 진단·챗봇 컨텍스트에 절대 싣지 않는다."""
    if not file_bytes.startswith(b"%PDF"):
        raise UnsupportedFileError("텍스트 PDF만 지원합니다")

    upload = SeteukUpload(
        user_id=user_id,
        status=UploadStatus.PROCESSING.value,
        file_name=file_name,
        content_type=content_type,
        size_bytes=len(file_bytes),
        content=file_bytes,
    )
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
    """생기부를 읽어 결과를 raw_result에 담는다. **기록에 반영하지는 않는다.**

    파싱과 반영을 나눈 이유는, 학생이 결과를 보고 무엇을 반영할지 고르는 검토 단계가
    있기 때문이다. 파서가 잘못 읽은 항목이나 이제 와서 넣고 싶지 않은 활동을 그대로
    밀어 넣지 않는다. `status=done`은 "읽어냈다"는 뜻이고, 실제 반영은
    `import_result`가 한다.
    """
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


async def get_upload_file(
    db: AsyncSession, user_id: uuid.UUID, upload_id: uuid.UUID
) -> SeteukUpload:
    """원본 내려받기용 조회. 파싱이 실패했어도 원본은 돌려준다 — 무엇을 올렸는지
    확인하는 것이 실패 원인을 짚는 첫걸음이기 때문이다."""
    upload = await get_upload(db, user_id, upload_id)
    if upload.content is None:
        raise UploadNotFoundError("보관된 원본이 없습니다")
    return upload


@dataclass
class ImportSelection:
    """무엇을 반영할지. 각 항목은 결과 배열의 index 목록이며, None이면 그 영역 전체다
    — 학생이 몇 개만 빼는 것이 보통이라 '지정 안 하면 전부'가 자연스럽다."""

    attendance: list[int] | None = None
    academic_performance: list[int] | None = None
    reading_activities: list[int] | None = None
    awards: list[int] | None = None
    volunteer_records: list[int] | None = None
    activities: list[int] | None = None


def _pick[T](items: list[T], chosen: list[int] | None) -> list[T]:
    if chosen is None:
        return list(items)
    # 범위 밖 index는 조용히 버린다 — 화면이 낡은 결과를 들고 있을 수 있다.
    return [items[i] for i in chosen if 0 <= i < len(items)]


async def import_result(
    db: AsyncSession,
    user_id: uuid.UUID,
    upload_id: uuid.UUID,
    selection: ImportSelection,
) -> dict[str, int]:
    """검토를 마친 결과 중 학생이 고른 것만 기록에 반영한다.

    재업로드와 마찬가지로, 이전 업로드에서 들어온 행은 지우고 새로 넣는다 — 직접
    입력한 행(source_upload_id가 비어 있는 것)은 건드리지 않는다. 같은 업로드를 다시
    반영하면 그 업로드의 이전 반영분을 대체한다.
    """
    upload = await get_upload(db, user_id, upload_id)
    if upload.status != UploadStatus.DONE.value or upload.raw_result is None:
        raise UploadNotReadyError("파싱이 완료되지 않았습니다")

    parsed = SeteukAnalysisResult.model_validate(upload.raw_result)
    chosen = SeteukAnalysisResult(
        attendance=_pick(parsed.attendance, selection.attendance),
        academic_performance=_pick(parsed.academic_performance, selection.academic_performance),
        reading_activities=_pick(parsed.reading_activities, selection.reading_activities),
        awards=_pick(parsed.awards, selection.awards),
        volunteer_records=_pick(parsed.volunteer_records, selection.volunteer_records),
        activities=_pick(parsed.activities, selection.activities),
        errors=parsed.errors,
    )

    await _replace_previous_upload_data(db, user_id)
    _persist_result(db, user_id, upload_id, chosen)
    upload.imported_at = datetime.now(UTC)
    await db.commit()

    return {
        "attendance": len(chosen.attendance),
        "academic_performance": len(chosen.academic_performance),
        "reading_activities": len(chosen.reading_activities),
        "awards": len(chosen.awards),
        "volunteer_records": len(chosen.volunteer_records),
        "activities": len(chosen.activities),
    }
