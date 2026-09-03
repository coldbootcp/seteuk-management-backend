"""3개년 서사 로드맵 — 생성·조회·재생성.

통합 결정 D-1에 따라 로드맵은 평면 계획 목록(`plan_items`)이 아니라 학년-학기마다
서사 단계를 갖는 6개 마디다. 재생성은 이전 버전을 지우지 않고 `superseded`로 남긴다 —
"기존 추천 및 로드맵 실행 기록은 덮어쓰지 않는다"는 원칙 때문이다.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import RoadmapNodeNotFoundError, RoadmapNotFoundError
from app.models.activity import Activity
from app.models.roadmap import (
    MatchType,
    ReconciliationLog,
    Roadmap,
    RoadmapNode,
    RoadmapNodeStatus,
    RoadmapPlanEvent,
    RoadmapStatus,
)
from app.models.user import User
from app.schemas.profile import FieldKey
from app.services.roadmap.reconciliation import judge
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


# --- 정합(Reconciliation) — 활동이 로드맵의 어디에 해당하는지 판정하고 진척을 옮긴다 ---


async def _career_terms(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    """정합 신호로 쓸 학생 자신의 진로 어휘. 원본 프로토타입이 반도체 단어를
    하드코딩했던 자리를 대신한다."""
    interests = await get_current_interests(db, user_id)
    terms: list[str] = list(interests.get(FieldKey.INTEREST_KEYWORDS) or [])
    department = interests.get(FieldKey.TARGET_DEPARTMENT)
    if department:
        terms.append(department)
    goal = interests.get(FieldKey.CAREER_GOAL) or {}
    if isinstance(goal, dict) and goal.get("goal"):
        terms.append(goal["goal"])
    return terms


async def _active_node(db: AsyncSession, roadmap_id: uuid.UUID) -> RoadmapNode | None:
    return await db.scalar(
        select(RoadmapNode)
        .where(
            RoadmapNode.roadmap_id == roadmap_id,
            RoadmapNode.status == RoadmapNodeStatus.ACTIVE.value,
        )
        .order_by(RoadmapNode.order_index.asc())
        .limit(1)
    )


async def _advance(db: AsyncSession, node: RoadmapNode, finished_status: str) -> None:
    """현재 노드를 닫고 다음 노드를 활성화한다. 다음 노드가 이미 지나간
    학기(skipped)면 건너뛰고 그다음을 찾는다."""
    node.status = finished_status
    following = await db.scalars(
        select(RoadmapNode)
        .where(
            RoadmapNode.roadmap_id == node.roadmap_id,
            RoadmapNode.order_index > node.order_index,
            RoadmapNode.status == RoadmapNodeStatus.PLANNED.value,
        )
        .order_by(RoadmapNode.order_index.asc())
        .limit(1)
    )
    following_node = following.first()
    if following_node is not None:
        following_node.status = RoadmapNodeStatus.ACTIVE.value


async def reconcile_activity(
    db: AsyncSession, user_id: uuid.UUID, activity: Activity
) -> ReconciliationLog | None:
    """활동 하나를 활성 로드맵과 대조한다. 로드맵이 아직 없으면 아무것도 하지 않는다 —
    로드맵을 만들기 전에 기록부터 쌓는 사용자를 막을 이유가 없다."""
    roadmap = await get_active_roadmap(db, user_id)
    if roadmap is None:
        return None

    node = await _active_node(db, roadmap.id)
    verdict = judge(
        activity_text=" ".join(
            [
                activity.activity_name,
                activity.description or "",
                activity.subject or "",
                *(activity.keywords or []),
            ]
        ),
        activity_subject=activity.subject or "",
        node=node,
        career_terms=await _career_terms(db, user_id),
    )

    log = ReconciliationLog(
        user_id=user_id,
        activity_id=activity.id,
        roadmap_id=roadmap.id,
        node_id=node.id if node else None,
        match_type=verdict.match_type,
        rationale=verdict.rationale,
        action=verdict.action,
        confidence=verdict.confidence,
    )
    db.add(log)

    if node is not None:
        if verdict.match_type == MatchType.MATCH.value:
            node.instantiated_activity_id = activity.id
            await _advance(db, node, RoadmapNodeStatus.DONE.value)
        elif verdict.match_type == MatchType.PARTIAL_MATCH.value:
            await _advance(db, node, RoadmapNodeStatus.PARTIAL.value)

    await db.commit()
    await db.refresh(log)
    return log


async def run_semester_checkpoint(db: AsyncSession, user: User) -> ReconciliationLog | None:
    """학기 체크포인트 — 이미 지나간(또는 지금 끝나는) 학기의 활성 노드에 완료 활동이
    없으면 MISS를 남긴다.

    MISS는 다른 판정과 달리 활동을 저장할 때가 아니라 **시간이 흘러서** 생긴다.
    그래서 여기서 노드 상태를 바꾸지 않는다 — 이월할지 건너뛸지는 학생이 정한다.
    """
    roadmap = await get_active_roadmap(db, user.id)
    if roadmap is None:
        return None
    node = await _active_node(db, roadmap.id)
    if node is None:
        return None

    # 아직 오지 않은 학기를 놓쳤다고 할 수는 없다. 활동이 노드를 충족해 다음 노드가
    # 활성화된 직후에도 체크포인트가 돌 수 있으므로, 시점 비교가 없으면 미래 학기에
    # 곧바로 MISS가 찍힌다.
    current = ((user.current_grade or 1), (user.current_semester or 1))
    if (node.grade, node.semester) > current:
        return None

    logged = await db.scalar(
        select(ReconciliationLog)
        .where(
            ReconciliationLog.node_id == node.id,
            ReconciliationLog.match_type.in_(
                [
                    MatchType.MATCH.value,
                    MatchType.PARTIAL_MATCH.value,
                    # 같은 노드에 MISS를 두 번 남기지 않는다 — 체크포인트는 여러 번
                    # 호출될 수 있다.
                    MatchType.MISS.value,
                ]
            ),
        )
        .limit(1)
    )
    if logged is not None:
        return None

    log = ReconciliationLog(
        user_id=user.id,
        activity_id=None,
        roadmap_id=roadmap.id,
        node_id=node.id,
        match_type=MatchType.MISS.value,
        rationale=(
            f"'{node.title}' 학기가 지나가는 동안 이 노드를 충족하는 활동이 기록되지 "
            "않았습니다."
        ),
        action="다음 학기로 이월할지 건너뛸지 학생이 결정",
        confidence=70,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log


async def list_reconciliations(
    db: AsyncSession, user_id: uuid.UUID, limit: int = 100
) -> list[ReconciliationLog]:
    rows = await db.scalars(
        select(ReconciliationLog)
        .where(ReconciliationLog.user_id == user_id)
        .order_by(ReconciliationLog.created_at.desc())
        .limit(limit)
    )
    return list(rows)
