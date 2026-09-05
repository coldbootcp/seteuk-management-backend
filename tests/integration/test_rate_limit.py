import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

import app.services.diagnosis_service as diagnosis_service
from app.core.config import get_settings
from app.models.usage_event import UsageEvent
from tests.conftest import TestSessionLocal


@pytest.fixture(autouse=True)
def _small_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    # 한도는 운영 환경에서만 자동으로 켜진다(개발 중 검증을 막지 않기 위해).
    # 이 테스트는 한도 자체를 검증하므로 명시적으로 켠다.
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "daily_diagnosis_limit", 2)
    monkeypatch.setattr(diagnosis_service, "AsyncSessionLocal", TestSessionLocal)


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def noop(diagnosis_id, user_id) -> None:
        return None

    monkeypatch.setattr(diagnosis_service, "run_diagnosis_job", noop)


async def test_diagnosis_is_capped_per_day(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    for _ in range(2):
        assert (
            await client.post("/api/v1/diagnosis", headers=auth_headers)
        ).status_code == 201

    blocked = await client.post("/api/v1/diagnosis", headers=auth_headers)
    assert blocked.status_code == 429
    assert blocked.json()["error_code"] == "RATE_LIMITED"


async def test_limit_is_per_user(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    for _ in range(2):
        await client.post("/api/v1/diagnosis", headers=auth_headers)

    signup = await client.post(
        "/api/v1/auth/signup",
        json={"email": "fresh-quota@example.com", "password": "s3cure-passw0rd"},
    )
    other = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    # 다른 사용자의 한도는 영향을 받지 않는다.
    assert (await client.post("/api/v1/diagnosis", headers=other)).status_code == 201


async def test_the_limit_is_off_outside_production(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """개발 중에는 같은 시나리오를 하루에도 수십 번 태운다. 그때 한도가 걸리면
    검증이 막히므로, 운영 환경이 아니면 기본적으로 풀어 둔다."""
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_enabled", None)
    monkeypatch.setattr(settings, "environment", "local")
    monkeypatch.setattr(settings, "daily_diagnosis_limit", 1)

    for _ in range(3):
        assert (
            await client.post("/api/v1/diagnosis", headers=auth_headers)
        ).status_code == 201

    # 한도가 꺼져 있어도 사용 기록은 남아야 한다 — 나중에 켰을 때 카운터가 비어
    # 있으면 그날 이미 쓴 만큼이 없던 일이 된다.
    async with TestSessionLocal() as db:
        used = await db.scalar(select(func.count()).select_from(UsageEvent))
    assert used == 3
