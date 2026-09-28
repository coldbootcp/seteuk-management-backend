"""record review consultation

Revision ID: 2a6c9e1f4b70
Revises: 1758394c6849
Create Date: 2026-09-28

설정 탭에서 올린 생기부에 이상·충돌이 있으면 상담(kind=record_review)으로 학생에게
확인받는다. 세션이 어떤 업로드를 확인하는지와 학생이 정한 반영 방법을 저장한다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "2a6c9e1f4b70"
down_revision: str | None = "1758394c6849"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "consultation_sessions",
        sa.Column("source_upload_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "consultation_sessions",
        sa.Column("record_decisions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_foreign_key(
        "consultation_sessions_source_upload_id_fkey",
        "consultation_sessions",
        "seteuk_uploads",
        ["source_upload_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "consultation_sessions_source_upload_id_fkey", "consultation_sessions", type_="foreignkey"
    )
    op.drop_column("consultation_sessions", "record_decisions")
    op.drop_column("consultation_sessions", "source_upload_id")
