"""오픈 전 대기자 메일주소 등록 — 중복 등록은 한 줄로 합치고 같은 응답을 준다."""

from httpx import AsyncClient
from sqlalchemy import func, select

from app.models.waitlist_entry import WaitlistEntry
from tests.conftest import TestSessionLocal


async def test_waitlist_stores_email_once(client: AsyncClient) -> None:
    for email in ("Wait@Example.com", "wait@example.com"):
        response = await client.post("/api/v1/auth/waitlist", json={"email": email})
        assert response.status_code == 200

    async with TestSessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(WaitlistEntry))
    assert count == 1


async def test_waitlist_rejects_invalid_email(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/waitlist", json={"email": "nope"})
    assert response.status_code == 422
