"""구글 로그인 — userinfo 조회는 구글 서버를 실제로 타야 하므로
_fetch_google_profile 경계만 모킹하고, 계정 생성·연결·이메일 인증 자동완료
로직은 실제로 태운다(카카오 로그인 테스트와 같은 경계 선택)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.user import User
from app.services import auth_service
from tests.conftest import TestSessionLocal


def _mock_fetch_profile(
    monkeypatch: pytest.MonkeyPatch, google_id: str, email: str | None
) -> None:
    async def _fake(google_access_token: str) -> tuple[str, str | None]:
        return google_id, email

    monkeypatch.setattr(auth_service, "_fetch_google_profile", _fake)


@pytest.mark.asyncio
async def test_new_google_user_is_created_and_email_pre_verified(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_fetch_profile(monkeypatch, "google-uid-1", "newbie@example.com")

    response = await client.post(
        "/api/v1/auth/social/google", json={"google_access_token": "fake"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_new_user"] is True

    async with TestSessionLocal() as db:
        user = await db.scalar(select(User).where(User.google_id == "google-uid-1"))
        assert user is not None
        assert user.email == "newbie@example.com"
        assert user.email_verified_at is not None


@pytest.mark.asyncio
async def test_google_login_links_to_existing_email_account_and_verifies_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await client.post(
        "/api/v1/auth/signup",
        json={"email": "already-signed-up@example.com", "password": "s3cure-passw0rd"},
    )
    async with TestSessionLocal() as db:
        user = await db.scalar(
            select(User).where(User.email == "already-signed-up@example.com")
        )
        assert user.email_verified_at is None

    _mock_fetch_profile(monkeypatch, "google-uid-2", "already-signed-up@example.com")
    response = await client.post(
        "/api/v1/auth/social/google", json={"google_access_token": "fake"}
    )
    assert response.status_code == 200
    assert response.json()["is_new_user"] is False

    async with TestSessionLocal() as db:
        user = await db.scalar(
            select(User).where(User.email == "already-signed-up@example.com")
        )
        assert user.google_id == "google-uid-2"
        assert user.email_verified_at is not None


@pytest.mark.asyncio
async def test_google_login_returning_user_reuses_account(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_fetch_profile(monkeypatch, "google-uid-3", "regular@example.com")
    first = await client.post(
        "/api/v1/auth/social/google", json={"google_access_token": "fake"}
    )
    second = await client.post(
        "/api/v1/auth/social/google", json={"google_access_token": "fake"}
    )

    assert first.json()["is_new_user"] is True
    assert second.json()["is_new_user"] is False

    async with TestSessionLocal() as db:
        count = len(
            list(await db.scalars(select(User).where(User.google_id == "google-uid-3")))
        )
        assert count == 1
