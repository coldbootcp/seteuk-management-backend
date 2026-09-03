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
from app.schemas.roadmap import (
    ReconciliationLogRead,
    RoadmapGenerateRequest,
    RoadmapNodeRead,
    RoadmapNodeUpdate,
    RoadmapPlanEventRead,
    RoadmapRead,
)
from app.services import roadmap_service

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
        db, user, focus_override=data.focus, career_track_override=data.career_track
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
