import pytest
from httpx import AsyncClient

import app.services.diagnosis_service as diagnosis_service
from app.core.config import get_settings
from tests.conftest import TestSessionLocal


@pytest.fixture(autouse=True)
def _small_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
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
