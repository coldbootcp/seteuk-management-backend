"""탭 관리 리소스의 공통 CRUD.

6개 리소스(출결/성적/독서/수상/봉사/활동)는 소유권 검사·필터·페이지네이션 규칙이
완전히 같아서, 리소스마다 서비스를 복사하는 대신 모델을 인자로 받는 한 벌로 처리한다.
모든 조회는 예외 없이 user_id로 먼저 좁히므로 남의 행에는 접근할 수 없다.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import UnaryExpression

from app.core.exceptions import RecordNotFoundError
from app.db.base import Base


async def list_records[T: Base](
    db: AsyncSession,
    model: type[T],
    user_id: uuid.UUID,
    *,
    filters: dict[str, Any],
    order_by: list[UnaryExpression],
    limit: int,
    offset: int,
) -> tuple[list[T], int]:
    conditions = [model.user_id == user_id]
    for column_name, value in filters.items():
        if value is not None:
            conditions.append(getattr(model, column_name) == value)

    total = await db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
    rows = await db.scalars(
        select(model).where(*conditions).order_by(*order_by).limit(limit).offset(offset)
    )
    return list(rows), total


async def get_record[T: Base](
    db: AsyncSession, model: type[T], user_id: uuid.UUID, record_id: uuid.UUID
) -> T:
    row = await db.scalar(select(model).where(model.id == record_id, model.user_id == user_id))
    if row is None:
        raise RecordNotFoundError("해당 기록을 찾을 수 없습니다")
    return row


async def create_record[T: Base](
    db: AsyncSession, model: type[T], user_id: uuid.UUID, data: dict[str, Any]
) -> T:
    # source_upload_id는 절대 받지 않는다 — 직접 입력한 행은 항상 null이어야
    # 생기부 재업로드 시 지워지지 않는다.
    row = model(user_id=user_id, **data)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def update_record[T: Base](
    db: AsyncSession, model: type[T], user_id: uuid.UUID, record_id: uuid.UUID, data: dict[str, Any]
) -> T:
    row = await get_record(db, model, user_id, record_id)
    for key, value in data.items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_record[T: Base](
    db: AsyncSession, model: type[T], user_id: uuid.UUID, record_id: uuid.UUID
) -> None:
    row = await get_record(db, model, user_id, record_id)
    await db.delete(row)
    await db.commit()
