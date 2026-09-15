"""회원 탈퇴 — 30일 유예 뒤 완전 삭제. 탈퇴 요청은 즉시 세션을 끊고 실제
기능을 막되, 유예 기간 안에는 취소할 수 있어야 한다."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.dependencies import get_active_verified_user
from app.main import app
from app.models.activity import Activity
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services import auth_service
from tests.conftest import TestSessionLocal, _bypass_active_verified_gate


@pytest.fixture(autouse=True)
def _use_real_gate():
    app.dependency_overrides.pop(get_active_verified_user, None)
    yield
    app.dependency_overrides[get_active_verified_user] = _bypass_active_verified_gate


async def _signup_and_verify(client: AsyncClient, email: str) -> tuple[dict[str, str], str]:
    signup = await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": "s3cure-passw0rd"}
    )
    user_id = signup.json()["user_id"]
    access = signup.json()["access_token"]
    refresh = signup.json()["refresh_token"]
    async with TestSessionLocal() as db:
        user = await db.get(User, user_id)
        user.email_verified_at = datetime.now(UTC)
        await db.commit()
    return {"Authorization": f"Bearer {access}"}, refresh


@pytest.mark.asyncio
async def test_withdraw_requires_correct_password(client: AsyncClient) -> None:
    headers, _ = await _signup_and_verify(client, "wrong-password@example.com")

    response = await client.post(
        "/api/v1/account/withdraw", headers=headers, json={"password": "not-the-password"}
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_withdraw_blocks_features_and_revokes_other_sessions(client: AsyncClient) -> None:
    headers, refresh_token = await _signup_and_verify(client, "withdrawing@example.com")

    response = await client.post(
        "/api/v1/account/withdraw", headers=headers, json={"password": "s3cure-passw0rd"}
    )
    assert response.status_code == 200
    assert response.json()["withdrawal_requested_at"] is not None

    blocked = await client.get("/api/v1/activities", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["error_code"] == "ACCOUNT_PENDING_DELETION"

    refreshed = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refreshed.status_code == 401


@pytest.mark.asyncio
async def test_cancel_withdrawal_restores_access(client: AsyncClient) -> None:
    headers, _ = await _signup_and_verify(client, "changed-mind@example.com")
    await client.post(
        "/api/v1/account/withdraw", headers=headers, json={"password": "s3cure-passw0rd"}
    )

    cancel = await client.post("/api/v1/account/cancel-withdrawal", headers=headers)
    assert cancel.status_code == 200
    assert cancel.json()["withdrawal_requested_at"] is None

    unlocked = await client.get("/api/v1/activities", headers=headers)
    assert unlocked.status_code == 200


@pytest.mark.asyncio
async def test_purge_deletes_only_accounts_past_the_grace_period(client: AsyncClient) -> None:
    _, _ = await _signup_and_verify(client, "purge-me@example.com")
    _, _ = await _signup_and_verify(client, "keep-me@example.com")

    async with TestSessionLocal() as db:
        overdue = await db.scalar(select(User).where(User.email == "purge-me@example.com"))
        recent = await db.scalar(select(User).where(User.email == "keep-me@example.com"))
        overdue.withdrawal_requested_at = datetime.now(UTC) - timedelta(days=31)
        recent.withdrawal_requested_at = datetime.now(UTC) - timedelta(days=1)
        await db.commit()

        purged_count = await auth_service.purge_withdrawn_accounts(db, grace_days=30)
        assert purged_count == 1

        remaining_emails = set(
            await db.scalars(select(User.email).where(User.email.in_([
                "purge-me@example.com", "keep-me@example.com"
            ])))
        )
        assert remaining_emails == {"keep-me@example.com"}


@pytest.mark.asyncio
async def test_purge_cascades_to_owned_data() -> None:
    """users FK에 건 ON DELETE CASCADE가 실제로 동작해, 완전 삭제 시 활동·
    refresh 토큰까지 함께 지워지는지 확인한다."""
    async with TestSessionLocal() as db:
        user = User(email="cascade@example.com", password_hash="x")
        db.add(user)
        await db.flush()
        activity = Activity(
            user_id=user.id,
            grade=1,
            activity_category="수행평가",
            activity_name="t",
            activity_type="report",
            description="d",
            keywords=[],
        )
        token = RefreshToken(user_id=user.id, expires_at=datetime.now(UTC) + timedelta(days=1))
        db.add_all([activity, token])
        user.withdrawal_requested_at = datetime.now(UTC) - timedelta(days=31)
        await db.commit()
        activity_id, token_id = activity.id, token.id

        purged_count = await auth_service.purge_withdrawn_accounts(db, grace_days=30)
        assert purged_count == 1

        # purge_withdrawn_accounts는 이 세션이 이미 들고 있던 activity/token
        # 객체를 몰라서(삭제는 DB의 ON DELETE CASCADE가 한 것이지 ORM cascade가
        # 한 게 아니다) identity map이 지워진 행을 그대로 캐싱하고 있다.
        # 실제 운영에서는 purge가 별도 세션(AsyncSessionLocal)을 쓰므로 이 문제가
        # 없다 — 테스트에서는 세션을 공유하니 명시적으로 새로 읽게 한다.
        db.expire_all()
        assert await db.get(Activity, activity_id) is None
        assert await db.get(RefreshToken, token_id) is None
