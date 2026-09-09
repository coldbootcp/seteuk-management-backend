from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

import app.services.maintenance_service as maintenance_service
from app.models.diagnosis import Diagnosis, DiagnosisStatus
from app.models.user import User
from tests.conftest import TestSessionLocal


@pytest.fixture(autouse=True)
def _patch_session_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(maintenance_service, "AsyncSessionLocal", TestSessionLocal)


async def test_stale_processing_jobs_are_failed_on_startup() -> None:
    async with TestSessionLocal() as db:
        user = User(email="stale@example.com")
        db.add(user)
        await db.flush()

        stale = Diagnosis(
            user_id=user.id,
            status=DiagnosisStatus.PROCESSING.value,
            created_at=datetime.now(UTC) - timedelta(hours=3),
        )
        recent = Diagnosis(user_id=user.id, status=DiagnosisStatus.PROCESSING.value)
        done = Diagnosis(user_id=user.id, status=DiagnosisStatus.DONE.value)
        db.add_all([stale, recent, done])
        await db.commit()
        stale_id, recent_id, done_id = stale.id, recent.id, done.id

    assert await maintenance_service.fail_stale_jobs() == 1

    async with TestSessionLocal() as db:
        rows = {
            d.id: d
            for d in await db.scalars(
                select(Diagnosis).where(Diagnosis.id.in_([stale_id, recent_id, done_id]))
            )
        }
    # 오래 멈춰 있던 것만 실패로 확정되고, 방금 시작한 job은 건드리지 않는다.
    assert rows[stale_id].status == "failed"
    assert rows[stale_id].failure_reason == maintenance_service.FAILURE_REASON
    assert rows[recent_id].status == "processing"
    assert rows[done_id].status == "done"
