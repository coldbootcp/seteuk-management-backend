"""3개년 서사 로드맵 — 생성·조회·재생성.

통합 결정 D-1에 따라 로드맵은 평면 계획 목록(`plan_items`)이 아니라 학년-학기마다
서사 단계를 갖는 6개 마디다. 재생성은 이전 버전을 지우지 않고 `superseded`로 남긴다 —
"기존 추천 및 로드맵 실행 기록은 덮어쓰지 않는다"는 원칙 때문이다.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import RoadmapNodeNotFoundError, RoadmapNotFoundError
from app.models.roadmap import (
    Roadmap,
    RoadmapNode,
    RoadmapNodeStatus,
    RoadmapPlanEvent,
    RoadmapStatus,
)
from app.models.user import User
from app.schemas.profile import FieldKey
from app.services.roadmap.templates import (
    NARRATIVE_STAGES,
    RETROSPECT_OBJECTIVE,
    RETROSPECT_STAGE,
    RETROSPECT_TITLE,
    TEMPLATE_ID,
    active_index,
    suggested_topics,
)
from app.services.student_interest_service import get_current_interests

DEFAULT_FOCUS = "관심 분야"


async def _resolve_focus(db: AsyncSession, user: User, override: str | None) -> tuple[str, str]:
    """로드맵 문구에 들어갈 관심 분야와 진로를 정한다.

    원본 프로토타입은 기본값이 "반도체 기술"이었지만, 백엔드는 특정 파일럿 도메인에
    묶이지 않아야 하므로 학생이 실제로 답한 값에서만 가져오고 없으면 중립어를 쓴다.
    """
    interests = await get_current_interests(db, user.id)
    keywords = interests.get(FieldKey.INTEREST_KEYWORDS) or []
    department = interests.get(FieldKey.TARGET_DEPARTMENT) or ""
    career_goal = interests.get(FieldKey.CAREER_GOAL) or {}
    goal = career_goal.get("goal", "") if isinstance(career_goal, dict) else ""

    focus = override or (keywords[0] if keywords else "") or department or goal or DEFAULT_FOCUS
    return focus, goal or department


async def get_active_roadmap(db: AsyncSession, user_id: uuid.UUID) -> Roadmap | None:
    return await db.scalar(
        select(Roadmap)
        .where(Roadmap.user_id == user_id, Roadmap.status != RoadmapStatus.SUPERSEDED.value)
        .order_by(Roadmap.version.desc())
        .limit(1)
    )


async def get_roadmap(db: AsyncSession, user_id: uuid.UUID, roadmap_id: uuid.UUID) -> Roadmap:
    roadmap = await db.scalar(
        select(Roadmap).where(Roadmap.id == roadmap_id, Roadmap.user_id == user_id)
    )
    if roadmap is None:
        raise RoadmapNotFoundError("로드맵을 찾을 수 없습니다")
    return roadmap


async def list_nodes(db: AsyncSession, roadmap_id: uuid.UUID) -> list[RoadmapNode]:
    rows = await db.scalars(
        select(RoadmapNode)
        .where(RoadmapNode.roadmap_id == roadmap_id)
        .order_by(RoadmapNode.order_index.asc())
    )
    return list(rows)


async def list_plan_events(db: AsyncSession, roadmap_id: uuid.UUID) -> list[RoadmapPlanEvent]:
    rows = await db.scalars(
        select(RoadmapPlanEvent)
        .where(RoadmapPlanEvent.roadmap_id == roadmap_id)
        .order_by(RoadmapPlanEvent.node_id, RoadmapPlanEvent.order_index.asc())
    )
    return list(rows)


async def generate_roadmap(
    db: AsyncSession,
    user: User,
    focus_override: str | None = None,
    career_track_override: str | None = None,
) -> Roadmap:
    """새 버전을 만들고 이전 활성 버전을 superseded로 내린다.

    현재 학기보다 앞선 마디는 새로 계획하지 않고 '회고'로 표시한다 — 이미 지나간
    학기에 계획을 제안해 봐야 학생이 할 수 있는 일이 없고, 그 자리는 생기부에서
    확인할 대상이기 때문이다.
    """
    focus, career = await _resolve_focus(db, user, focus_override)
    career_track = career_track_override or career

    previous = await get_active_roadmap(db, user.id)
    if previous is not None:
        previous.status = RoadmapStatus.SUPERSEDED.value

    roadmap = Roadmap(
        user_id=user.id,
        version=(previous.version + 1) if previous else 1,
        career_track=career_track,
        template_id=TEMPLATE_ID,
        status=RoadmapStatus.DRAFT.value,
    )
    db.add(roadmap)
    await db.flush()

    current = active_index(user.current_grade or 1, user.current_semester or 1)

    for index, stage in enumerate(NARRATIVE_STAGES):
        past = index < current
        node = RoadmapNode(
            roadmap_id=roadmap.id,
            user_id=user.id,
            order_index=index,
            grade=stage.grade,
            semester=stage.semester,
            narrative_stage=RETROSPECT_STAGE if past else stage.stage,
            title=(
                RETROSPECT_TITLE
                if past
                else (f"{focus} 관점으로 {stage.title}" if index == current else stage.title)
            ),
            objective=RETROSPECT_OBJECTIVE if past else stage.objective,
            candidate_subjects=[] if past else list(stage.subjects),
            competency_goals=[] if past else list(stage.competencies),
            status=(
                RoadmapNodeStatus.SKIPPED.value
                if past
                else (
                    RoadmapNodeStatus.ACTIVE.value
                    if index == current
                    else RoadmapNodeStatus.PLANNED.value
                )
            ),
        )
        db.add(node)
        await db.flush()

        if past:
            continue
        for topic in suggested_topics(focus, stage):
            db.add(
                RoadmapPlanEvent(
                    roadmap_id=roadmap.id,
                    node_id=node.id,
                    user_id=user.id,
                    **topic,
                )
            )

    await db.commit()
    await db.refresh(roadmap)
    return roadmap


async def update_node(
    db: AsyncSession, user_id: uuid.UUID, node_id: uuid.UUID, fields: dict
) -> RoadmapNode:
    """학생이 미리보기에서 제목·목표를 직접 고치는 경로. 제안은 제안일 뿐이다."""
    node = await db.scalar(
        select(RoadmapNode).where(RoadmapNode.id == node_id, RoadmapNode.user_id == user_id)
    )
    if node is None:
        raise RoadmapNodeNotFoundError("로드맵 마디를 찾을 수 없습니다")
    for key, value in fields.items():
        if value is not None:
            setattr(node, key, value)
    await db.commit()
    await db.refresh(node)
    return node


async def confirm_roadmap(db: AsyncSession, user_id: uuid.UUID, roadmap_id: uuid.UUID) -> Roadmap:
    """미리보기(draft)를 확정해 활성 로드맵으로 만든다."""
    roadmap = await get_roadmap(db, user_id, roadmap_id)
    roadmap.status = RoadmapStatus.ACTIVE.value
    await db.commit()
    await db.refresh(roadmap)
    return roadmap
