"""탭 관리(Phase 4) 라우터.

6개 리소스가 같은 CRUD 형태를 가지므로 라우터를 손으로 6번 쓰는 대신 팩토리로
찍어낸다. 라우터는 여전히 검증 → 서비스 호출 → 응답 변환만 담당하고, 실제 로직은
record_service에 있다.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import UnaryExpression

from app.core.dependencies import get_current_user
from app.core.rate_limit import enforce_daily_limit
from app.db.base import Base
from app.db.session import get_db
from app.models.academic_performance import AcademicPerformance
from app.models.activity import Activity
from app.models.attendance import Attendance
from app.models.award import Award
from app.models.reading_activity import ReadingActivity
from app.models.usage_event import UsageAction
from app.models.user import User
from app.models.volunteer_record import VolunteerRecord
from app.schemas.records import (
    AcademicPerformanceCreate,
    AcademicPerformanceRead,
    AcademicPerformanceUpdate,
    ActivityCreate,
    ActivityLineageResponse,
    ActivityRead,
    ActivityUpdate,
    AttendanceCreate,
    AttendanceRead,
    AttendanceUpdate,
    AwardCreate,
    AwardRead,
    AwardUpdate,
    ListResponse,
    ReadingActivityCreate,
    ReadingActivityRead,
    ReadingActivityUpdate,
    VolunteerRecordCreate,
    VolunteerRecordRead,
    VolunteerRecordUpdate,
)
from app.schemas.roadmap import ActivityReviewRead
from app.services import (
    activity_lineage_service,
    activity_review_service,
    record_service,
    roadmap_service,
)


class Pagination(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class AttendanceFilters(Pagination):
    grade: int | None = None


class AcademicPerformanceFilters(Pagination):
    grade: int | None = None
    semester: int | None = None
    subject: str | None = None
    category: str | None = None


class ReadingActivityFilters(Pagination):
    grade: int | None = None
    semester: int | None = None
    subject: str | None = None


class AwardFilters(Pagination):
    pass


class VolunteerRecordFilters(Pagination):
    grade: int | None = None


class ActivityFilters(Pagination):
    grade: int | None = None
    semester: int | None = None
    activity_category: str | None = None
    activity_type: str | None = None
    subject: str | None = None


def build_record_router(
    *,
    prefix: str,
    tag: str,
    model: type[Base],
    create_schema: type[BaseModel],
    update_schema: type[BaseModel],
    read_schema: type[BaseModel],
    filter_schema: type[Pagination],
    order_by: Callable[[], list[UnaryExpression]],
    after_create: Callable[[AsyncSession, User, Any], Awaitable[None]] | None = None,
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[tag])

    @router.get("", response_model=ListResponse[read_schema])
    async def list_records(
        filters: Annotated[filter_schema, Query()],
        user: Annotated[User, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> Any:
        conditions = filters.model_dump(exclude={"limit", "offset"})
        rows, total = await record_service.list_records(
            db,
            model,
            user.id,
            filters=conditions,
            order_by=order_by(),
            limit=filters.limit,
            offset=filters.offset,
        )
        return ListResponse[read_schema](
            items=[read_schema.model_validate(row) for row in rows], total=total
        )

    @router.post("", response_model=read_schema, status_code=status.HTTP_201_CREATED)
    async def create_record(
        data: create_schema,
        user: Annotated[User, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> Any:
        row = await record_service.create_record(db, model, user.id, data.model_dump())
        if after_create is not None:
            await after_create(db, user, row)
        return read_schema.model_validate(row)

    @router.get("/{record_id}", response_model=read_schema)
    async def get_record(
        record_id: uuid.UUID,
        user: Annotated[User, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> Any:
        row = await record_service.get_record(db, model, user.id, record_id)
        return read_schema.model_validate(row)

    @router.patch("/{record_id}", response_model=read_schema)
    async def update_record(
        record_id: uuid.UUID,
        data: update_schema,
        user: Annotated[User, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> Any:
        row = await record_service.update_record(
            db, model, user.id, record_id, data.model_dump(exclude_unset=True)
        )
        return read_schema.model_validate(row)

    @router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_record(
        record_id: uuid.UUID,
        user: Annotated[User, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> None:
        await record_service.delete_record(db, model, user.id, record_id)

    return router


attendance_router = build_record_router(
    prefix="/attendance",
    tag="attendance",
    model=Attendance,
    create_schema=AttendanceCreate,
    update_schema=AttendanceUpdate,
    read_schema=AttendanceRead,
    filter_schema=AttendanceFilters,
    order_by=lambda: [Attendance.grade.asc()],
)

academic_performance_router = build_record_router(
    prefix="/academic-performance",
    tag="academic-performance",
    model=AcademicPerformance,
    create_schema=AcademicPerformanceCreate,
    update_schema=AcademicPerformanceUpdate,
    read_schema=AcademicPerformanceRead,
    filter_schema=AcademicPerformanceFilters,
    order_by=lambda: [
        AcademicPerformance.grade.asc(),
        AcademicPerformance.semester.asc(),
        AcademicPerformance.subject.asc(),
    ],
)

reading_activity_router = build_record_router(
    prefix="/reading-activities",
    tag="reading-activities",
    model=ReadingActivity,
    create_schema=ReadingActivityCreate,
    update_schema=ReadingActivityUpdate,
    read_schema=ReadingActivityRead,
    filter_schema=ReadingActivityFilters,
    order_by=lambda: [
        ReadingActivity.grade.asc(),
        ReadingActivity.semester.asc(),
        ReadingActivity.title.asc(),
    ],
)

award_router = build_record_router(
    prefix="/awards",
    tag="awards",
    model=Award,
    create_schema=AwardCreate,
    update_schema=AwardUpdate,
    read_schema=AwardRead,
    filter_schema=AwardFilters,
    order_by=lambda: [Award.date.asc().nullslast(), Award.name.asc()],
)

volunteer_record_router = build_record_router(
    prefix="/volunteer-records",
    tag="volunteer-records",
    model=VolunteerRecord,
    create_schema=VolunteerRecordCreate,
    update_schema=VolunteerRecordUpdate,
    read_schema=VolunteerRecordRead,
    filter_schema=VolunteerRecordFilters,
    order_by=lambda: [VolunteerRecord.grade.asc(), VolunteerRecord.date.asc().nullslast()],
)

async def _reconcile_new_activity(db: AsyncSession, user: User, row: Any) -> None:
    """활동을 저장하면 곧바로 활성 로드맵과 대조한다. 로드맵이 없으면 조용히 넘어간다 —
    로드맵을 만들기 전에 기록부터 쌓는 것을 막을 이유가 없다."""
    await roadmap_service.reconcile_activity(db, user, row)


activity_router = build_record_router(
    prefix="/activities",
    tag="activities",
    model=Activity,
    create_schema=ActivityCreate,
    update_schema=ActivityUpdate,
    read_schema=ActivityRead,
    filter_schema=ActivityFilters,
    order_by=lambda: [
        Activity.grade.asc(),
        Activity.semester.asc().nullsfirst(),
        Activity.created_at.asc(),
    ],
    after_create=_reconcile_new_activity,
)


@activity_router.get("/{activity_id}/lineage", response_model=ActivityLineageResponse)
async def get_activity_lineage(
    activity_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ActivityLineageResponse:
    """이 활동이 속한 사슬 전체 — 뿌리까지 거슬러 올라간 뒤 후손 활동과
    아직 실행되지 않은 계획까지 함께 돌려준다."""
    nodes = await activity_lineage_service.get_lineage(db, user.id, activity_id)
    return ActivityLineageResponse(nodes=nodes)


record_routers = [
    attendance_router,
    academic_performance_router,
    reading_activity_router,
    award_router,
    volunteer_record_router,
    activity_router,
]


@activity_router.post(
    "/{activity_id}/review",
    response_model=ActivityReviewRead,
    status_code=status.HTTP_201_CREATED,
)
async def review_activity(
    activity_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ActivityReviewRead:
    """이 활동이 생기부에 어떻게 남을지 검토한다 — 근거·빈 곳·다음 한 걸음.
    로드맵 진척을 옮기는 정합 판정과 달리, 이건 학생에게 방향을 준다."""
    await enforce_daily_limit(db, user.id, UsageAction.CHAT_MESSAGE)
    review = await activity_review_service.review_activity(db, user.id, activity_id)
    return ActivityReviewRead.model_validate(review)


@activity_router.get("/reviews/history", response_model=list[ActivityReviewRead])
async def list_activity_reviews(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ActivityReviewRead]:
    """활동별 가장 최근 검토."""
    rows = await activity_review_service.list_reviews(db, user.id)
    return [ActivityReviewRead.model_validate(row) for row in rows]
