"""consultation flow stage and chat titles

상담을 "3개년 흐름 → 이번 학기 목표 → 구체 주제" 순서로 진행하기 위한 세션 컬럼과,
대화 제목의 출처(title_source)를 추가한다. 기존 상담 대화는 첫 메시지를 잘라 만든
제목을 달고 있어, 목적에 맞는 기본 제목으로 바꾼다(학생이 고친 제목은 아직 없다 —
이름 바꾸기는 이 리비전에서 처음 생긴다).

Revision ID: b3e7a1c9d24f
Revises: ae35c4f6d712
Create Date: 2026-09-27 19:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b3e7a1c9d24f"
down_revision: str | Sequence[str] | None = "ae35c4f6d712"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "consultation_sessions",
        sa.Column("draft_flow", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "consultation_sessions",
        sa.Column("flow_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "consultation_sessions",
        sa.Column("semester_goal", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("title_source", sa.String(length=10), nullable=True),
    )

    op.execute(
        """
        UPDATE conversations
        SET title = '3개년 흐름 설계', title_source = 'default'
        WHERE purpose = 'initial_consultation'
        """
    )
    op.execute(
        """
        UPDATE conversations
        SET title = '목표 학과 지원 전략', title_source = 'default'
        WHERE purpose = 'graduate_fit_consultation'
        """
    )
    op.execute(
        """
        UPDATE conversations AS c
        SET title = s.target_grade || '학년 ' || s.target_semester || '학기 점검',
            title_source = 'default'
        FROM consultation_sessions AS s
        WHERE s.conversation_id = c.id
          AND c.purpose = 'semester_review_consultation'
        """
    )
    # 진행 중이던 상담이 이전 방식으로 3개년 계획 전체를 담은 초안(full_replan)을
    # 들고 있을 수 있다. 새 흐름은 3개년 흐름부터 학생이 확정해야 하므로, 끝나지 않은
    # 세션의 그런 초안은 비워 흐름 단계부터 다시 시작하게 한다. 확정된 세션과
    # 이번 학기만 고치는 재평가 초안(current_node_only)은 건드리지 않는다.
    op.execute(
        """
        UPDATE consultation_sessions
        SET draft_plan = NULL, status = 'in_progress', ready_at = NULL
        WHERE status IN ('in_progress', 'ready')
          AND (kind = 'initial' OR draft_plan ->> 'mode' = 'full_replan')
        """
    )
    # 남은 것은 재평가의 이번 학기 초안뿐이다 — 그 초안이 담은 이번 학기 목표를 새
    # semester_goal 칸으로 옮겨, 학생이 이미 합의한 목표를 다시 묻지 않게 한다.
    op.execute(
        """
        UPDATE consultation_sessions
        SET semester_goal = draft_plan -> 'current_node'
        WHERE status IN ('in_progress', 'ready')
          AND draft_plan IS NOT NULL
          AND semester_goal IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("conversations", "title_source")
    op.drop_column("consultation_sessions", "semester_goal")
    op.drop_column("consultation_sessions", "flow_confirmed_at")
    op.drop_column("consultation_sessions", "draft_flow")
