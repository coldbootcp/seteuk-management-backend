from datetime import UTC, datetime, timedelta

from app.models.user import User
from app.services.student_interest_service import get_current_interests, upsert_interest
from tests.conftest import TestSessionLocal


async def _create_user(db) -> User:
    user = User(email="interest-test@example.com", password_hash="x")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def test_upsert_interest_creates_new_row_for_first_answer() -> None:
    async with TestSessionLocal() as db:
        user = await _create_user(db)
        entry = await upsert_interest(db, user.id, "career_goal", {"goal": "의사"})
        await db.commit()

        assert entry.value == {"goal": "의사"}


async def test_upsert_interest_overwrites_within_seven_days_and_keeps_answered_at() -> None:
    async with TestSessionLocal() as db:
        user = await _create_user(db)
        first = await upsert_interest(db, user.id, "career_goal", {"goal": "의사"})
        await db.commit()
        original_answered_at = first.answered_at

        second = await upsert_interest(db, user.id, "career_goal", {"goal": "AI 연구원"})
        await db.commit()

        assert second.id == first.id
        assert second.value == {"goal": "AI 연구원"}
        assert second.answered_at == original_answered_at

        current = await get_current_interests(db, user.id)
        assert current["career_goal"] == {"goal": "AI 연구원"}


async def test_upsert_interest_creates_new_row_after_seven_days() -> None:
    async with TestSessionLocal() as db:
        user = await _create_user(db)
        first = await upsert_interest(db, user.id, "career_goal", {"goal": "의사"})
        # 8일 전에 답한 것처럼 시간을 되돌려서 7일 규칙 경계를 넘겼는지 확인.
        first.answered_at = datetime.now(UTC) - timedelta(days=8)
        await db.commit()

        second = await upsert_interest(db, user.id, "career_goal", {"goal": "AI 연구원"})
        await db.commit()

        assert second.id != first.id

        rows = await get_current_interests(db, user.id)
        assert rows["career_goal"] == {"goal": "AI 연구원"}
