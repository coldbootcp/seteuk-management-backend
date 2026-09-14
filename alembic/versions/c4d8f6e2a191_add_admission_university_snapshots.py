"""add admission university statistic snapshots

Revision ID: c4d8f6e2a191
Revises: b7d9e3a4f4d2
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c4d8f6e2a191"
down_revision: str | Sequence[str] | None = "b7d9e3a4f4d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admission_university_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("university_id", sa.UUID(), nullable=False),
        sa.Column("source_admission_year", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["university_id"], ["universities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "university_id",
            "source_admission_year",
            name="uq_admission_university_snapshot_year",
        ),
    )
    op.create_index(
        op.f("ix_admission_university_snapshots_source_admission_year"),
        "admission_university_snapshots",
        ["source_admission_year"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admission_university_snapshots_university_id"),
        "admission_university_snapshots",
        ["university_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_admission_university_snapshots_university_id"),
        table_name="admission_university_snapshots",
    )
    op.drop_index(
        op.f("ix_admission_university_snapshots_source_admission_year"),
        table_name="admission_university_snapshots",
    )
    op.drop_table("admission_university_snapshots")
