"""활동 계보 — 3년에 걸쳐 하나의 활동이 어떻게 고도화됐는지 추적한다.

기록된 활동은 `activities.parent_activity_id`로, 아직 실행되지 않은 계획은
`plan_items.source_activity_id`로 사슬에 매달린다. 이미 완료 처리돼 활동으로
승격된 계획은 그 활동 노드로 대체되므로 계보에 중복해서 넣지 않는다.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ActivityNotFoundError
from app.models.activity import Activity
from app.models.plan_item import PlanItem
from app.schemas.records import ActivityLineageNode


def _root_of(activity_id: uuid.UUID, parent_of: dict[uuid.UUID, uuid.UUID | None]) -> uuid.UUID:
    seen: set[uuid.UUID] = set()
    current = activity_id
    while True:
        parent = parent_of.get(current)
        # 부모가 없거나, 남의/삭제된 행을 가리키거나, 순환이면 여기가 뿌리.
        if parent is None or parent not in parent_of or parent in seen:
            return current
        seen.add(current)
        current = parent


async def get_lineage(
    db: AsyncSession, user_id: uuid.UUID, activity_id: uuid.UUID
) -> list[ActivityLineageNode]:
    activities = list(await db.scalars(select(Activity).where(Activity.user_id == user_id)))
    by_id = {a.id: a for a in activities}
    if activity_id not in by_id:
        raise ActivityNotFoundError("활동을 찾을 수 없습니다")

    parent_of = {a.id: a.parent_activity_id for a in activities}
    children: dict[uuid.UUID | None, list[Activity]] = {}
    for activity in activities:
        children.setdefault(activity.parent_activity_id, []).append(activity)

    root = _root_of(activity_id, parent_of)

    chain: list[Activity] = []
    queue = [by_id[root]]
    while queue:
        node = queue.pop(0)
        chain.append(node)
        queue.extend(children.get(node.id, []))

    chain_ids = {a.id for a in chain}
    nodes = [
        ActivityLineageNode(
            kind="activity",
            id=a.id,
            title=a.activity_name,
            grade=a.grade,
            semester=a.semester,
            status="completed",
            parent_id=a.parent_activity_id if a.parent_activity_id in chain_ids else None,
        )
        for a in chain
    ]

    plans = await db.scalars(
        select(PlanItem).where(
            PlanItem.user_id == user_id,
            PlanItem.source_activity_id.in_(chain_ids),
            PlanItem.completed_activity_id.is_(None),
        )
    )
    nodes.extend(
        ActivityLineageNode(
            kind="plan",
            id=p.id,
            title=p.title,
            grade=p.target_grade,
            semester=p.target_semester,
            status=p.status,
            parent_id=p.source_activity_id,
        )
        for p in plans
    )

    nodes.sort(key=lambda n: (n.grade or 0, n.semester or 0, n.kind))
    return nodes
