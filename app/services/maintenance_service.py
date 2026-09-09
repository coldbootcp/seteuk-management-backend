"""프로세스가 죽으면서 남은 좀비 job 정리.

파싱과 진단은 BackgroundTasks(같은 프로세스)로 돌기 때문에, 배포나 크래시로
프로세스가 내려가면 그 job은 영영 끝나지 않고 status가 processing에 멈춘다.
클라이언트는 그 화면에서 무한 대기하게 되므로, 기동할 때 오래된 processing 행을
실패로 확정해 사용자가 다시 시도할 수 있게 한다.
"""

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import update

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.diagnosis import Diagnosis, DiagnosisStatus
from app.models.seteuk_upload import SeteukUpload, UploadStatus

logger = structlog.get_logger()

FAILURE_REASON = "서버가 재시작되어 작업이 중단되었습니다. 다시 시도해주세요."


async def fail_stale_jobs() -> int:
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(minutes=settings.stale_job_timeout_minutes)
    total = 0

    async with AsyncSessionLocal() as db:
        for model, processing, failed in (
            (SeteukUpload, UploadStatus.PROCESSING, UploadStatus.FAILED),
            (Diagnosis, DiagnosisStatus.PROCESSING, DiagnosisStatus.FAILED),
        ):
            result = await db.execute(
                update(model)
                .where(model.status == processing.value, model.created_at < cutoff)
                .values(status=failed.value, failure_reason=FAILURE_REASON)
            )
            total += result.rowcount or 0
        await db.commit()

    if total:
        logger.warning("marked stale jobs as failed", count=total)
    return total
