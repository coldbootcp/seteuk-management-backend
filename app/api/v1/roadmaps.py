import uuid
from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.exceptions import RoadmapNotFoundError
from app.core.rate_limit import enforce_daily_limit
from app.db.session import get_db
from app.models.roadmap import Roadmap
from app.models.usage_event import UsageAction
from app.models.user import User
from app.schemas.plan import AdoptPlanEventRequest, PlanItemRead
from app.schemas.records import AcademicPerformanceRead
from app.schemas.roadmap import (
    NodeSummaryResponse,
    ReconciliationLogRead,
    RoadmapGenerateRequest,
    RoadmapNodeRead,
    RoadmapNodeUpdate,
    RoadmapPlanEventRead,
    RoadmapRead,
)
from app.services import plan_service, roadmap_service

router = APIRouter(prefix="/roadmaps", tags=["roadmaps"])


async def _assemble(db: AsyncSession, roadmap: Roadmap) -> RoadmapRead:
    """마디와 그 안의 제안 주제를 한 응답으로 묶는다. 화면이 학기별로 펼쳐 보여주므로
    노드마다 이벤트가 붙어 있어야 왕복이 줄어든다."""
    nodes = await roadmap_service.list_nodes(db, roadmap.id)
    events = await roadmap_service.list_plan_events(db, roadmap.id)

    by_node: dict[uuid.UUID, list[RoadmapPlanEventRead]] = defaultdict(list)
    for event in events:
        by_node[event.node_id].append(RoadmapPlanEventRead.model_validate(event))

    result = RoadmapRead.model_validate(roadmap)
    result.nodes = [
        RoadmapNodeRead.model_validate(node).model_copy(
            update={"plan_events": by_node.get(node.id, [])}
        )
        for node in nodes
    ]
    return result


@router.post("", response_model=RoadmapRead, status_code=status.HTTP_201_CREATED)
async def generate_roadmap(
    data: RoadmapGenerateRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RoadmapRead:
    """새 로드맵 버전을 만든다. 이전 활성 버전은 지워지지 않고 superseded로 남는다."""
    await enforce_daily_limit(db, user.id, UsageAction.ROADMAP)
    roadmap = await roadmap_service.generate_roadmap(
        db,
        user,
        focus_override=data.focus,
        career_track_override=data.career_track,
        grade_override=data.grade,
        semester_override=data.semester,
    )
    return await _assemble(db, roadmap)


@router.get("/active", response_model=RoadmapRead)
async def get_active_roadmap(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RoadmapRead:
    roadmap = await roadmap_service.get_active_roadmap(db, user.id)
    if roadmap is None:
        raise RoadmapNotFoundError("아직 만들어진 로드맵이 없습니다")
    return await _assemble(db, roadmap)


@router.get("/{roadmap_id}", response_model=RoadmapRead)
async def get_roadmap(
    roadmap_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RoadmapRead:
    roadmap = await roadmap_service.get_roadmap(db, user.id, roadmap_id)
    return await _assemble(db, roadmap)


@router.post("/{roadmap_id}/confirm", response_model=RoadmapRead)
async def confirm_roadmap(
    roadmap_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RoadmapRead:
    """학생이 미리보기를 검토한 뒤 확정한다."""
    roadmap = await roadmap_service.confirm_roadmap(db, user.id, roadmap_id)
    return await _assemble(db, roadmap)


@router.patch("/nodes/{node_id}", response_model=RoadmapNodeRead)
async def update_node(
    node_id: uuid.UUID,
    data: RoadmapNodeUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RoadmapNodeRead:
    node = await roadmap_service.update_node(db, user.id, node_id, data.model_dump())
    return RoadmapNodeRead.model_validate(node)


@router.get("/reconciliations/history", response_model=list[ReconciliationLogRead])
async def list_reconciliations(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ReconciliationLogRead]:
    """판정 이력. 활동 타임라인 옆에 "이 활동이 로드맵의 어디였는지"를 붙여 보여준다."""
    rows = await roadmap_service.list_reconciliations(db, user.id)
    return [ReconciliationLogRead.model_validate(row) for row in rows]


@router.post("/checkpoint", response_model=ReconciliationLogRead | None)
async def run_checkpoint(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReconciliationLogRead | None:
    """학기 체크포인트. 활성 노드에 완료 활동이 없으면 MISS를 남긴다 — 활동 저장이
    아니라 시간이 흘러서 생기는 판정이라 별도 경로다. 남길 것이 없으면 null."""
    log = await roadmap_service.run_semester_checkpoint(db, user)
    return ReconciliationLogRead.model_validate(log) if log else None


@router.get("/nodes/{node_id}/courses", response_model=list[AcademicPerformanceRead])
async def list_node_courses(
    node_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AcademicPerformanceRead]:
    """이 학기 마디를 위해 듣는 과목들.

    별도 테이블을 두지 않고 `academic_performance`에 `roadmap_node_id`를 붙이는
    방식이다(D-3). 성적 레코드를 둘로 나누면 진단의 학기별 평균 석차등급이 어느
    쪽을 봐야 할지 모호해지기 때문이다 — 과목은 하나고, 로드맵 연결은 그 과목에
    붙는 속성이다.
    """
    rows = await roadmap_service.list_node_courses(db, user.id, node_id)
    return [AcademicPerformanceRead.model_validate(row) for row in rows]


@router.get("/nodes/{node_id}/plans", response_model=list[PlanItemRead])
async def list_node_plans(
    node_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PlanItemRead]:
    """이 마디에 매달린 계획들. 제안 주제(`plan_events`)가 고를 후보라면, 이건 실제로
    하기로 한 것이다."""
    rows = await roadmap_service.list_node_plans(db, user.id, node_id)
    return [PlanItemRead.model_validate(row) for row in rows]


@router.post(
    "/plan-events/{event_id}/adopt",
    response_model=PlanItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def adopt_plan_event(
    event_id: uuid.UUID,
    data: AdoptPlanEventRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PlanItemRead:
    """마디의 제안 주제를 계획으로 담는다. 제안은 지우지 않고 그대로 남는다 —
    학생이 나중에 다른 것을 골라 담을 수 있어야 하기 때문이다."""
    event = await roadmap_service.get_plan_event(db, user.id, event_id)
    plan = await plan_service.adopt_plan_event(db, user.id, event, data)
    return PlanItemRead.model_validate(plan)


@router.post("/nodes/{node_id}/summarize", response_model=NodeSummaryResponse)
async def summarize_node(
    node_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> NodeSummaryResponse:
    """이 학기 마디가 어떻게 채워졌는지 요약한다. 그 학기의 활동만 근거로 쓰고,
    없으면 없다고 쓴다."""
    await enforce_daily_limit(db, user.id, UsageAction.CHAT_MESSAGE)
    return NodeSummaryResponse(summary=await roadmap_service.summarize_node(db, user.id, node_id))
