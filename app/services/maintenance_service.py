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
from app.services import auth_service

logger = structlog.get_logger()

FAILURE_REASON = "서버가 재시작되어 작업이 중단되었습니다. 다시 시도해주세요."


async def purge_stale_withdrawals() -> int:
    """탈퇴 유예 기간이 지난 계정을 완전히 삭제한다. 별도 워커 큐가 없으므로
    (CLAUDE.md 잔여 과제) 좀비 job 정리와 같은 패턴으로 기동 시 한 번 돈다 —
    트래픽이 늘면 주기적 스케줄러로 옮겨야 정확한 30일 시점에 삭제된다."""
    settings = get_settings()
    async with AsyncSessionLocal() as db:
        count = await auth_service.purge_withdrawn_accounts(
            db, settings.account_deletion_grace_days
        )
    if count:
        logger.info("purged withdrawn accounts", count=count)
    return count


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
