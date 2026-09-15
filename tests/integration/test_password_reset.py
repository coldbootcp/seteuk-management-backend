"""비밀번호 재설정 — 토큰 단일 사용, 만료, 재설정 후 다른 세션 전체 로그아웃."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import hash_opaque_token
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.services import email_service
from tests.conftest import TestSessionLocal


@pytest.fixture
def sent_reset_emails(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def _fake_send(to: str, token: str) -> None:
        sent.append({"to": to, "token": token})

    monkeypatch.setattr(email_service, "send_password_reset_email", _fake_send)
    return sent


async def _signup(client: AsyncClient, email: str, password: str = "s3cure-passw0rd") -> str:
    response = await client.post("/api/v1/auth/signup", json={"email": email, "password": password})
    return response.json()["refresh_token"]


@pytest.mark.asyncio
async def test_reset_password_rejects_weak_password(
    client: AsyncClient, sent_reset_emails: list[dict[str, Any]]
) -> None:
    await _signup(client, "weakpw@example.com")
    await client.post("/api/v1/auth/password/forgot", json={"email": "weakpw@example.com"})
    token = sent_reset_emails[0]["token"]

    response = await client.post(
        "/api/v1/auth/password/reset", json={"token": token, "new_password": "short1"}
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "WEAK_PASSWORD"


@pytest.mark.asyncio
async def test_reset_password_changes_credentials_and_revokes_other_sessions(
    client: AsyncClient, sent_reset_emails: list[dict[str, Any]]
) -> None:
    old_refresh = await _signup(client, "reset-me@example.com")
    await client.post("/api/v1/auth/password/forgot", json={"email": "reset-me@example.com"})
    token = sent_reset_emails[0]["token"]

    reset = await client.post(
        "/api/v1/auth/password/reset", json={"token": token, "new_password": "n3w-passw0rd"}
    )
    assert reset.status_code == 200

    old_login = await client.post(
        "/api/v1/auth/login", json={"email": "reset-me@example.com", "password": "s3cure-passw0rd"}
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        "/api/v1/auth/login", json={"email": "reset-me@example.com", "password": "n3w-passw0rd"}
    )
    assert new_login.status_code == 200

    stale_refresh = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert stale_refresh.status_code == 401


@pytest.mark.asyncio
async def test_reset_token_is_single_use(
    client: AsyncClient, sent_reset_emails: list[dict[str, Any]]
) -> None:
    await _signup(client, "reuse-reset@example.com")
    await client.post("/api/v1/auth/password/forgot", json={"email": "reuse-reset@example.com"})
    token = sent_reset_emails[0]["token"]

    first = await client.post(
        "/api/v1/auth/password/reset", json={"token": token, "new_password": "n3w-passw0rd"}
    )
    assert first.status_code == 200

    second = await client.post(
        "/api/v1/auth/password/reset", json={"token": token, "new_password": "another-p4ss"}
    )
    assert second.status_code == 400
    assert second.json()["error_code"] == "INVALID_RESET_TOKEN"


@pytest.mark.asyncio
async def test_expired_reset_token_is_rejected(client: AsyncClient) -> None:
    await _signup(client, "expired-token@example.com")
    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == "expired-token@example.com"))
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_opaque_token("raw-expired-token"),
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        await db.commit()

    response = await client.post(
        "/api/v1/auth/password/reset",
        json={"token": "raw-expired-token", "new_password": "n3w-passw0rd"},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_RESET_TOKEN"


@pytest.mark.asyncio
async def test_forgot_password_does_not_leak_whether_email_exists(client: AsyncClient) -> None:
    await _signup(client, "known@example.com")

    known = await client.post("/api/v1/auth/password/forgot", json={"email": "known@example.com"})
    unknown = await client.post(
        "/api/v1/auth/password/forgot", json={"email": "nobody-at-all@example.com"}
    )
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
