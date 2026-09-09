"""진단+상담 필수 관문 — 관문 판정, 세션 생성/재사용, 확정(conclude).

큰 계획의 저장소는 새로 만들지 않는다. 확정 전까지는 ConsultationSession.draft_plan
(JSONB)에만 쌓이다가, 확정(conclude) 순간에만 트랜잭션 하나로 기존 roadmap_nodes/
roadmap_plan_events에 반영된다 — "버튼을 누르기 전까지는 확정이 아니다"는 요구를
그대로 구현한 것이다.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConsultationNotReadyError,
    ConsultationSessionNotFoundError,
    ProfileIncompleteError,
)
from app.models.consultation import ConsultationKind, ConsultationSession, ConsultationStatus
from app.models.conversation import Conversation, ConversationPurpose
from app.models.roadmap import (
    Roadmap,
    RoadmapNode,
    RoadmapNodeStatus,
    RoadmapPlanEvent,
    RoadmapStatus,
)
from app.models.user import User
from app.schemas.consultation import ConsultationStatusResponse, DraftPlan
from app.services.roadmap.templates import (
    NARRATIVE_STAGES,
    RETROSPECT_OBJECTIVE,
    RETROSPECT_STAGE,
    RETROSPECT_TITLE,
    TEMPLATE_ID,
    active_index,
)
from app.services.roadmap_service import get_active_roadmap, list_nodes


async def has_concluded_for_period(
    db: AsyncSession, user_id: uuid.UUID, grade: int, semester: int
) -> bool:
    existing = await db.scalar(
        select(ConsultationSession.id).where(
            ConsultationSession.user_id == user_id,
            ConsultationSession.status == ConsultationStatus.CONCLUDED.value,
            ConsultationSession.target_grade == grade,
            ConsultationSession.target_semester == semester,
        )
    )
    return existing is not None


async def has_ever_concluded(db: AsyncSession, user_id: uuid.UUID) -> bool:
    existing = await db.scalar(
        select(ConsultationSession.id)
        .where(
            ConsultationSession.user_id == user_id,
            ConsultationSession.status == ConsultationStatus.CONCLUDED.value,
        )
        .limit(1)
    )
    return existing is not None


async def get_status(db: AsyncSession, user: User) -> ConsultationStatusResponse:
    if user.current_grade is None or user.current_semester is None:
        return ConsultationStatusResponse(satisfied=True)

    grade, semester = user.current_grade, user.current_semester
    if await has_concluded_for_period(db, user.id, grade, semester):
        return ConsultationStatusResponse(satisfied=True)

    required_kind = (
        "initial" if not await has_ever_concluded(db, user.id) else "semester_review"
    )
    resumable = await db.scalar(
        select(ConsultationSession)
        .where(
            ConsultationSession.user_id == user.id,
            ConsultationSession.kind == required_kind,
            ConsultationSession.target_grade == grade,
            ConsultationSession.target_semester == semester,
            ConsultationSession.status.in_(
                [ConsultationStatus.IN_PROGRESS.value, ConsultationStatus.READY.value]
            ),
        )
        .order_by(ConsultationSession.created_at.desc())
        .limit(1)
    )
    return ConsultationStatusResponse(
        satisfied=False,
        required_kind=required_kind,
        target_grade=grade,
        target_semester=semester,
        resumable_session_id=resumable.id if resumable else None,
    )


async def get_or_create_session(db: AsyncSession, user: User) -> ConsultationSession:
    """학생의 현재 선언 학기에 맞는 세션을 재사용하거나 새로 만든다. generate_roadmap의
    '미완성 draft는 지우고 다시 쓴다'는 관용구 대신, 여기서는 진행 중인 세션이 있으면
    그대로 이어쓴다 — 상담 대화 자체가 대화 기록이라 버릴 이유가 없다."""
    if user.current_grade is None or user.current_semester is None:
        raise ProfileIncompleteError("프로필(학년-학기)을 먼저 설정해주세요")

    status = await get_status(db, user)
    if status.satisfied:
        raise ConsultationNotReadyError("이미 이번 학기 상담이 완료되어 있습니다")

    if status.resumable_session_id is not None:
        session = await db.get(ConsultationSession, status.resumable_session_id)
        if session is not None:
            return session

    kind = (
        ConsultationKind.INITIAL.value
        if status.required_kind == "initial"
        else ConsultationKind.SEMESTER_REVIEW.value
    )
    purpose = (
        ConversationPurpose.INITIAL_CONSULTATION.value
        if kind == ConsultationKind.INITIAL.value
        else ConversationPurpose.SEMESTER_REVIEW_CONSULTATION.value
    )
    conversation = Conversation(user_id=user.id, purpose=purpose)
    db.add(conversation)
    await db.flush()

    session = ConsultationSession(
        user_id=user.id,
        conversation_id=conversation.id,
        kind=kind,
        target_grade=user.current_grade,
        target_semester=user.current_semester,
        status=ConsultationStatus.IN_PROGRESS.value,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_active_plan_summary(db: AsyncSession, user: User) -> list[dict] | None:
    """재평가 상담에 넘길 '기존 3개년 계획' 요약. 최초 상담(아직 로드맵 없음)은 None."""
    roadmap = await get_active_roadmap(db, user.id)
    if roadmap is None:
        return None
    nodes = await list_nodes(db, roadmap.id)
    return [
        {
            "grade": n.grade,
            "semester": n.semester,
            "narrative_stage": n.narrative_stage,
            "title": n.title,
            "objective": n.objective,
            "status": n.status,
            "candidate_subjects": n.candidate_subjects,
            "competency_goals": n.competency_goals,
        }
        for n in nodes
    ]


async def get_session(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID
) -> ConsultationSession:
    session = await db.scalar(
        select(ConsultationSession).where(
            ConsultationSession.id == session_id, ConsultationSession.user_id == user_id
        )
    )
    if session is None:
        raise ConsultationSessionNotFoundError("상담 세션을 찾을 수 없습니다")
    return session


async def confirm_full_replan(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID, confirmed: bool
) -> ConsultationSession:
    """재평가 상담 도중 챗봇이 '전체 재설계'를 제안했을 때, 대화 텍스트가 아니라
    이 명시적 엔드포인트로만 동의를 받는다."""
    session = await get_session(db, user_id, session_id)
    if confirmed:
        session.full_replan_confirmed_at = datetime.now(UTC)
    else:
        session.full_replan_confirmed_at = None
        if session.draft_plan and session.draft_plan.get("mode") == "full_replan":
            # 동의를 철회하면 이미 담긴 전체 재설계 초안도 함께 버린다 — 동의 없이
            # 전체 계획이 남아 있으면 다음 propose_draft_plan 검증을 우회할 여지가 있다.
            session.draft_plan = None
    await db.commit()
    await db.refresh(session)
    return session


def _current_index(target_grade: int, target_semester: int) -> int:
    return active_index(target_grade, target_semester)


async def _apply_full_replan(
    db: AsyncSession, user: User, session: ConsultationSession, draft: DraftPlan
) -> None:
    if len(draft.nodes) != len(NARRATIVE_STAGES):
        raise ConsultationNotReadyError(
            f"큰 계획은 {len(NARRATIVE_STAGES)}개 마디여야 합니다"
        )

    previous = await get_active_roadmap(db, user.id)
    version = 1
    if previous is not None:
        previous.status = RoadmapStatus.SUPERSEDED.value
        version = previous.version + 1

    roadmap = Roadmap(
        user_id=user.id,
        version=version,
        career_track=draft.career_track,
        template_id=TEMPLATE_ID,
        status=RoadmapStatus.ACTIVE.value,
    )
    db.add(roadmap)
    await db.flush()

    current = _current_index(session.target_grade, session.target_semester)
    for index, node_draft in enumerate(draft.nodes):
        past = index < current
        is_current = index == current
        # current_node이 '이번 학기 목표'의 단일 진실 공급원이다 — nodes[current]도
        # 같은 내용을 채워 오겠지만, 둘이 어긋나면 current_node를 따른다.
        title = draft.current_node.title if is_current else node_draft.title
        objective = draft.current_node.objective if is_current else node_draft.objective
        candidate_subjects = (
            draft.current_node.candidate_subjects if is_current else node_draft.candidate_subjects
        )
        competency_goals = (
            draft.current_node.competency_goals if is_current else node_draft.competency_goals
        )
        node = RoadmapNode(
            roadmap_id=roadmap.id,
            user_id=user.id,
            order_index=index,
            grade=node_draft.grade,
            semester=node_draft.semester,
            narrative_stage=RETROSPECT_STAGE if past else node_draft.narrative_stage,
            title=RETROSPECT_TITLE if past else title,
            objective=RETROSPECT_OBJECTIVE if past else objective,
            candidate_subjects=[] if past else list(candidate_subjects),
            competency_goals=[] if past else list(competency_goals),
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

        if index == current:
            # 현재 마디만 상담에서 함께 만든 10개 제안을 바로 얹는다 — 나머지 마디는
            # 그 마디가 실제로 '현재'가 될 재평가 때 채워진다(몇 년 뒤 학기까지
            # 미리 만들어 둘 이유가 없다).
            for event in draft.plan_events:
                db.add(
                    RoadmapPlanEvent(
                        roadmap_id=roadmap.id,
                        node_id=node.id,
                        user_id=user.id,
                        order_index=event.order_index,
                        month_day=event.month_day,
                        category=event.category,
                        subject=event.subject,
                        priority=event.priority,
                        title=event.title,
                        description=event.description,
                    )
                )


async def _apply_current_node_only(
    db: AsyncSession, user: User, session: ConsultationSession, draft: DraftPlan
) -> None:
    roadmap = await get_active_roadmap(db, user.id)
    if roadmap is None:
        raise ConsultationNotReadyError(
            "기존 큰 계획이 없어 현재 학기 목표만 조정할 수 없습니다"
        )
    node = await db.scalar(
        select(RoadmapNode).where(
            RoadmapNode.roadmap_id == roadmap.id,
            RoadmapNode.grade == session.target_grade,
            RoadmapNode.semester == session.target_semester,
        )
    )
    if node is None:
        raise ConsultationNotReadyError("이번 학기에 해당하는 로드맵 마디를 찾을 수 없습니다")

    node.title = draft.current_node.title
    node.objective = draft.current_node.objective
    node.candidate_subjects = list(draft.current_node.candidate_subjects)
    node.competency_goals = list(draft.current_node.competency_goals)
    if node.status not in (RoadmapNodeStatus.DONE.value, RoadmapNodeStatus.PARTIAL.value):
        node.status = RoadmapNodeStatus.ACTIVE.value

    existing_events = await db.scalars(
        select(RoadmapPlanEvent).where(RoadmapPlanEvent.node_id == node.id)
    )
    for existing in existing_events:
        await db.delete(existing)
    await db.flush()

    for event in draft.plan_events:
        db.add(
            RoadmapPlanEvent(
                roadmap_id=roadmap.id,
                node_id=node.id,
                user_id=user.id,
                order_index=event.order_index,
                month_day=event.month_day,
                category=event.category,
                subject=event.subject,
                priority=event.priority,
                title=event.title,
                description=event.description,
            )
        )


async def conclude(
    db: AsyncSession, user: User, session: ConsultationSession
) -> ConsultationSession:
    """도구 호출의 부수효과가 아니라 오직 이 함수(POST .../conclude)로만 실행된다.
    챗봇이 signal_ready_to_conclude를 부른 뒤 학생이 실제로 나가기 버튼을 눌러야
    한다는 요구를 그대로 구현한다."""
    if session.status != ConsultationStatus.READY.value or session.draft_plan is None:
        raise ConsultationNotReadyError(
            "아직 상담이 끝나지 않았습니다 — 챗봇이 준비됐다는 신호를 보내야 합니다"
        )

    draft = DraftPlan.model_validate(session.draft_plan)
    if draft.mode == "full_replan":
        await _apply_full_replan(db, user, session, draft)
    else:
        await _apply_current_node_only(db, user, session, draft)

    session.status = ConsultationStatus.CONCLUDED.value
    session.concluded_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(session)
    return session
