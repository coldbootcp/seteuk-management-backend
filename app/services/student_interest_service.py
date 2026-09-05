import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.student_interest import StudentInterest

OVERWRITE_WINDOW = timedelta(days=7)


async def upsert_interest(
    db: AsyncSession, user_id: uuid.UUID, field_key: str, value: Any
) -> StudentInterest:
    """Writes the user's own answer for field_key. If the latest existing row for
    this (user_id, field_key) was answered within the last 7 days, its value is
    overwritten in place and answered_at is kept — a same-week correction is treated
    as the same declaration, not a new era. Otherwise a fresh row is inserted,
    preserving the field's history."""
    latest = await db.scalar(
        select(StudentInterest)
        .where(StudentInterest.user_id == user_id, StudentInterest.field_key == field_key)
        .order_by(StudentInterest.answered_at.desc())
        .limit(1)
    )

    now = datetime.now(UTC)
    if latest is not None and now - latest.answered_at < OVERWRITE_WINDOW:
        latest.value = value
        latest.updated_at = now
        await db.flush()
        return latest

    entry = StudentInterest(user_id=user_id, field_key=field_key, value=value)
    db.add(entry)
    await db.flush()
    return entry


async def get_current_interests(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """Returns only the latest value per field_key for this user."""
    rows = await db.scalars(
        select(StudentInterest)
        .where(StudentInterest.user_id == user_id)
        .order_by(StudentInterest.field_key, StudentInterest.answered_at.desc())
    )

    current: dict[str, Any] = {}
    for row in rows:
        current.setdefault(row.field_key, row.value)
    return current
