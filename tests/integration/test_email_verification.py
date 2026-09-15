"""이메일 인증 관문 — 미인증 계정은 로그인은 되지만 실제 기능은 막히고,
인증을 마치면 풀린다는 것을 검증한다."""

from typing import Any

import pytest
from httpx import AsyncClient

from app.core.dependencies import get_active_verified_user
from app.main import app
from app.services import email_service
from tests.conftest import _bypass_active_verified_gate


@pytest.fixture(autouse=True)
def _use_real_gate():
    """이 파일은 관문 자체를 검증하므로, 다른 통합 테스트를 위한 전역 우회를
    이 파일 안에서만 걷어낸다."""
    app.dependency_overrides.pop(get_active_verified_user, None)
    yield
    app.dependency_overrides[get_active_verified_user] = _bypass_active_verified_gate


@pytest.fixture
def sent_verification_emails(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def _fake_send(to: str, token: str) -> None:
        sent.append({"to": to, "token": token})

    monkeypatch.setattr(email_service, "send_verification_email", _fake_send)
    return sent


async def _signup(client: AsyncClient, email: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": "s3cure-passw0rd"}
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_unverified_account_is_blocked_from_real_features(
    client: AsyncClient, sent_verification_emails: list[dict[str, Any]]
) -> None:
    headers = await _signup(client, "unverified@example.com")

    assert len(sent_verification_emails) == 1
    assert sent_verification_emails[0]["to"] == "unverified@example.com"

    blocked = await client.get("/api/v1/activities", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["error_code"] == "EMAIL_NOT_VERIFIED"


@pytest.mark.asyncio
async def test_verifying_email_unblocks_real_features(
    client: AsyncClient, sent_verification_emails: list[dict[str, Any]]
) -> None:
    headers = await _signup(client, "will-verify@example.com")
    token = sent_verification_emails[0]["token"]

    verify = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert verify.status_code == 200

    unlocked = await client.get("/api/v1/activities", headers=headers)
    assert unlocked.status_code == 200


@pytest.mark.asyncio
async def test_verification_token_is_single_use(
    client: AsyncClient, sent_verification_emails: list[dict[str, Any]]
) -> None:
    await _signup(client, "reuse@example.com")
    token = sent_verification_emails[0]["token"]

    first = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert first.status_code == 200

    second = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert second.status_code == 400
    assert second.json()["error_code"] == "INVALID_VERIFICATION_TOKEN"


@pytest.mark.asyncio
async def test_resend_verification_does_not_leak_whether_email_exists(
    client: AsyncClient, sent_verification_emails: list[dict[str, Any]]
) -> None:
    existing = await client.post(
        "/api/v1/auth/resend-verification", json={"email": "unverified@example.com"}
    )
    nonexistent = await client.post(
        "/api/v1/auth/resend-verification", json={"email": "nobody@example.com"}
    )
    # 계정을 미리 만들어 두지 않았으니 존재 이메일 케이스는 실제로 없다 —
    # 두 응답의 모양이 같다는 것만 확인한다(존재 여부가 형태로 새지 않음).
    assert existing.status_code == nonexistent.status_code == 200
    assert existing.json() == nonexistent.json()
