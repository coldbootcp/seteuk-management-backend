"""ACCESS_ALLOWLIST로 닫은 환경(dev)에서 목록 밖 계정이 가입·로그인·인증 요청을 못 하는지."""

import pytest
from httpx import AsyncClient

import app.services.auth_service as auth_service
from app.core.config import get_settings

ALLOWED = "allowed@example.com"
OTHER = "stranger@example.com"
PASSWORD = "s3cure-passw0rd"


def _allow_only(monkeypatch: pytest.MonkeyPatch, emails: str) -> None:
    monkeypatch.setattr(get_settings(), "access_allowlist", emails)


def _fake_google(monkeypatch: pytest.MonkeyPatch, email: str | None) -> None:
    async def _fake(token: str) -> tuple[str, str | None]:
        return "google-sub-1", email

    monkeypatch.setattr(auth_service, "_fetch_google_profile", _fake)


async def test_empty_allowlist_keeps_signup_open(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/signup", json={"email": OTHER, "password": PASSWORD})
    assert response.status_code == 201


async def test_signup_outside_allowlist_is_rejected_without_creating_account(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_only(monkeypatch, ALLOWED)

    rejected = await client.post("/api/v1/auth/signup", json={"email": OTHER, "password": PASSWORD})
    assert rejected.status_code == 403
    assert rejected.json()["error_code"] == "ACCESS_NOT_ALLOWED"

    # 계정이 만들어지지 않았으니, 목록을 비운 뒤에는 같은 이메일로 새로 가입할 수 있다.
    _allow_only(monkeypatch, "")
    retry = await client.post("/api/v1/auth/signup", json={"email": OTHER, "password": PASSWORD})
    assert retry.status_code == 201


async def test_allowlisted_email_matches_case_insensitively(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_only(monkeypatch, " Allowed@Example.com , someone@example.com")
    response = await client.post(
        "/api/v1/auth/signup", json={"email": ALLOWED, "password": PASSWORD}
    )
    assert response.status_code == 201


async def test_existing_account_is_locked_out_once_allowlist_is_set(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 목록을 켜기 전에 가입해 둔 계정.
    signup = await client.post("/api/v1/auth/signup", json={"email": OTHER, "password": PASSWORD})
    tokens = signup.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    _allow_only(monkeypatch, ALLOWED)

    login = await client.post("/api/v1/auth/login", json={"email": OTHER, "password": PASSWORD})
    assert login.status_code == 403

    refresh = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh.status_code == 403

    # 이미 받아 둔 access 토큰으로도 인증이 필요한 API를 쓸 수 없다.
    me = await client.get("/api/v1/account/status", headers=headers)
    assert me.status_code == 403
    assert me.json()["error_code"] == "ACCESS_NOT_ALLOWED"


async def test_wrong_password_still_reports_invalid_credentials(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await client.post("/api/v1/auth/signup", json={"email": OTHER, "password": PASSWORD})
    _allow_only(monkeypatch, ALLOWED)
    # 비밀번호가 틀리면 허용 여부를 드러내지 않고 평소처럼 401을 준다.
    response = await client.post(
        "/api/v1/auth/login", json={"email": OTHER, "password": "wrong-passw0rd"}
    )
    assert response.status_code == 401


async def test_google_login_outside_allowlist_is_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_only(monkeypatch, ALLOWED)
    _fake_google(monkeypatch, OTHER)
    response = await client.post("/api/v1/auth/social/google", json={"google_access_token": "t"})
    assert response.status_code == 403

    _fake_google(monkeypatch, ALLOWED)
    allowed = await client.post("/api/v1/auth/social/google", json={"google_access_token": "t"})
    assert allowed.status_code == 200
