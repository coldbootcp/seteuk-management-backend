"""add admission university guides

Revision ID: f1c3e9a8b702
Revises: d7a3b2f9e4c6
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f1c3e9a8b702"
down_revision: str | Sequence[str] | None = "d7a3b2f9e4c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admission_university_guides",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("university_id", sa.UUID(), nullable=False),
        sa.Column("source_admission_year", sa.Integer(), nullable=False),
        sa.Column("sections", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
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
            name="uq_admission_university_guide_year",
        ),
    )
    op.create_index(
        op.f("ix_admission_university_guides_university_id"),
        "admission_university_guides",
        ["university_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admission_university_guides_source_admission_year"),
        "admission_university_guides",
        ["source_admission_year"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_admission_university_guides_source_admission_year"),
        table_name="admission_university_guides",
    )
    op.drop_index(
        op.f("ix_admission_university_guides_university_id"),
        table_name="admission_university_guides",
    )
    op.drop_table("admission_university_guides")
