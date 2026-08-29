from typing import Any

import httpx
import pytest
from httpx import AsyncClient

import app.services.auth_service as auth_service


def _patch_kakao(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], status: int = 200):
    """카카오 호출만 가로챈다 — 테스트 클라이언트도 같은 AsyncClient.get을 쓰므로
    다른 URL은 원래 구현으로 흘려보내야 한다."""
    original_get = httpx.AsyncClient.get

    async def fake_get(self, url, **kwargs):  # noqa: ANN001
        if str(url) != auth_service.KAKAO_USER_INFO_URL:
            return await original_get(self, url, **kwargs)
        return httpx.Response(status, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


async def test_kakao_login_creates_user_on_first_visit(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_kakao(monkeypatch, {"id": 12345, "kakao_account": {"email": "kakao@example.com"}})

    first = await client.post(
        "/api/v1/auth/social/kakao", json={"kakao_access_token": "valid-token"}
    )
    assert first.status_code == 200
    assert first.json()["is_new_user"] is True

    second = await client.post(
        "/api/v1/auth/social/kakao", json={"kakao_access_token": "valid-token"}
    )
    assert second.json()["is_new_user"] is False

    # 발급된 access 토큰이 실제로 인증에 쓸 수 있어야 한다.
    headers = {"Authorization": f"Bearer {second.json()['access_token']}"}
    assert (await client.get("/api/v1/profile/me", headers=headers)).status_code == 200


async def test_kakao_login_links_to_existing_email_account(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await client.post(
        "/api/v1/auth/signup",
        json={"email": "linked@example.com", "password": "s3cure-passw0rd"},
    )
    _patch_kakao(monkeypatch, {"id": 999, "kakao_account": {"email": "linked@example.com"}})

    response = await client.post(
        "/api/v1/auth/social/kakao", json={"kakao_access_token": "valid-token"}
    )
    # 같은 이메일이면 계정을 새로 만들지 않고 연결한다.
    assert response.json()["is_new_user"] is False


async def test_kakao_login_without_email_consent_still_works(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_kakao(monkeypatch, {"id": 777})
    response = await client.post(
        "/api/v1/auth/social/kakao", json={"kakao_access_token": "valid-token"}
    )
    assert response.status_code == 200
    assert response.json()["is_new_user"] is True


async def test_invalid_kakao_token_is_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_kakao(monkeypatch, {"msg": "invalid token"}, status=401)
    response = await client.post(
        "/api/v1/auth/social/kakao", json={"kakao_access_token": "bad-token"}
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "SOCIAL_AUTH_FAILED"
