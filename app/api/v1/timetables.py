"""학생 시간표 동기화 API."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_active_verified_user, get_current_user
from app.core.exceptions import RecordNotFoundError
from app.db.session import get_db
from app.models.timetable import Timetable
from app.models.user import User
from app.schemas.timetable import TimetableListResponse, TimetableRead, TimetableReplaceRequest

router = APIRouter(
    prefix="/timetables",
    tags=["timetables"],
    dependencies=[Depends(get_active_verified_user)],
)


@router.get("", response_model=TimetableListResponse)
async def list_timetables(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TimetableListResponse:
    rows = list(
        await db.scalars(
            select(Timetable)
            .where(Timetable.user_id == user.id)
            .order_by(Timetable.grade.asc(), Timetable.semester.asc(), Timetable.created_at.asc())
        )
    )
    return TimetableListResponse(timetables=[TimetableRead.model_validate(row) for row in rows])


@router.put("", response_model=TimetableListResponse)
async def replace_timetables(
    data: TimetableReplaceRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TimetableListResponse:
    """학생의 시간표 목록을 원자적으로 동기화한다.

    프론트는 시간표 안에서 슬롯을 옮기거나 여러 칸을 한 번에 추가한다. 매 조작마다
    부분 API를 여러 번 보내면 중간 실패로 한 과목의 반복 배치가 깨질 수 있어, 화면의
    완성된 목록 하나를 저장 단위로 삼는다. 서버 UUID가 아닌 id를 보내 수정하려 하면
    다른 학생 행을 건드리는 대신 명시적으로 거절한다.
    """
    existing = list(
        await db.scalars(select(Timetable).where(Timetable.user_id == user.id))
    )
    by_id = {row.id: row for row in existing}
    submitted_ids = {item.id for item in data.timetables if item.id is not None}
    unknown_ids = submitted_ids - set(by_id)
    if unknown_ids:
        raise RecordNotFoundError("동기화할 시간표를 찾을 수 없습니다")

    rows: list[Timetable] = []
    for item in data.timetables:
        values = item.model_dump(exclude={"id"})
        values["slots"] = [slot.model_dump() for slot in item.slots]
        if item.id is None:
            row = Timetable(user_id=user.id, **values)
            db.add(row)
        else:
            row = by_id[item.id]
            for key, value in values.items():
                setattr(row, key, value)
        rows.append(row)

    # 목록에서 사라진 것은 학생이 화면에서 삭제한 시간표다. user_id 조건이 있어
    # 다른 계정의 행은 어떤 경우에도 삭제되지 않는다.
    removed_ids = set(by_id) - submitted_ids
    if removed_ids:
        await db.execute(
            delete(Timetable).where(Timetable.user_id == user.id, Timetable.id.in_(removed_ids))
        )

    await db.commit()
    # 새 UUID와 updated_at을 읽어 응답한다.
    saved = list(
        await db.scalars(
            select(Timetable)
            .where(Timetable.user_id == user.id)
            .order_by(Timetable.grade.asc(), Timetable.semester.asc(), Timetable.created_at.asc())
        )
    )
    return TimetableListResponse(timetables=[TimetableRead.model_validate(row) for row in saved])
