"""add student timetables

Revision ID: ae35c4f6d712
Revises: 703dc533d48e
Create Date: 2026-09-23 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "ae35c4f6d712"
down_revision: str | Sequence[str] | None = "703dc533d48e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "timetables",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("grade", sa.Integer(), nullable=False),
        sa.Column("semester", sa.Integer(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("slots", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_timetables_user_id"), "timetables", ["user_id"], unique=False)
    op.create_index(
        "ix_timetables_user_period", "timetables", ["user_id", "grade", "semester"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_timetables_user_period", table_name="timetables")
    op.drop_index(op.f("ix_timetables_user_id"), table_name="timetables")
    op.drop_table("timetables")
