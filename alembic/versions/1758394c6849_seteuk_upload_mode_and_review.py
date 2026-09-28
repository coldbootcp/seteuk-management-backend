"""seteuk upload mode and review

Revision ID: 1758394c6849
Revises: c5f2d8e1a9b3
Create Date: 2026-09-28

설정 탭의 생기부 올리기·교체(mode=replace)는 이상·충돌이 없으면 서버가 바로
반영하고, 있으면 대조 결과(review)를 남기고 멈춘다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "1758394c6849"
down_revision: str | None = "c5f2d8e1a9b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "seteuk_uploads",
        sa.Column("mode", sa.String(length=20), server_default="onboarding", nullable=False),
    )
    op.add_column(
        "seteuk_uploads",
        sa.Column("review", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("seteuk_uploads", "review")
    op.drop_column("seteuk_uploads", "mode")
