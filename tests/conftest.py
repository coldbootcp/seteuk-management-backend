from collections.abc import AsyncGenerator
from typing import Annotated

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.dependencies import (
    get_active_verified_user,
    get_current_user,
    require_consultation_satisfied,
)
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import User

TEST_DATABASE_URL = get_settings().database_url.rsplit("/", 1)[0] + "/seteuk_test"

test_engine = create_async_engine(TEST_DATABASE_URL)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def _prepare_database() -> AsyncGenerator[None]:
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _override_get_db() -> AsyncGenerator[AsyncSession]:
    async with TestSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = _override_get_db


async def _bypass_consultation_gate(user: Annotated[User, Depends(get_current_user)]) -> User:
    """대부분의 기존 통합 테스트는 로드맵/계획/기록 자체를 검증하는 것이지 진단+상담
    관문을 검증하는 게 아니므로, 기본적으로 관문을 통과시킨다. 관문 자체를 검증하는
    테스트(test_consultation.py)는 이 오버라이드를 일시적으로 제거하고 실제
    require_consultation_satisfied를 쓴다."""
    return user


app.dependency_overrides[require_consultation_satisfied] = _bypass_consultation_gate


async def _bypass_active_verified_gate(user: Annotated[User, Depends(get_current_user)]) -> User:
    """대부분의 기존 통합 테스트는 이메일 인증·탈퇴 유예 상태 자체를 검증하는 게
    아니므로 기본적으로 통과시킨다. 이 게이트 자체를 검증하는 테스트
    (test_email_verification.py, test_account_withdrawal.py)는 이 오버라이드를
    일시적으로 제거하고 실제 get_active_verified_user를 쓴다."""
    return user


app.dependency_overrides[get_active_verified_user] = _bypass_active_verified_gate


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/signup",
        json={"email": "seteuk-tester@example.com", "password": "s3cure-passw0rd"},
    )
    access_token = response.json()["access_token"]
    return {"Authorization": f"Bearer {access_token}"}
