"""add admission program references and outcomes

Revision ID: d7a3b2f9e4c6
Revises: c4d8f6e2a191
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d7a3b2f9e4c6"
down_revision: str | Sequence[str] | None = "c4d8f6e2a191"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admission_program_references",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("university_id", sa.UUID(), nullable=False),
        sa.Column("source_admission_year", sa.Integer(), nullable=False),
        sa.Column("source_reference_code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("academic_field", sa.String(length=80), nullable=True),
        sa.Column("recruitment_count", sa.Integer(), nullable=True),
        sa.Column("early_competition_rate", sa.Float(), nullable=True),
        sa.Column("regular_competition_rate", sa.Float(), nullable=True),
        sa.Column("detail_sections", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
            "source_reference_code",
            name="uq_admission_program_reference_source",
        ),
    )
    op.create_index(
        op.f("ix_admission_program_references_university_id"),
        "admission_program_references",
        ["university_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admission_program_references_source_admission_year"),
        "admission_program_references",
        ["source_admission_year"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admission_program_references_source_reference_code"),
        "admission_program_references",
        ["source_reference_code"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admission_program_references_name"),
        "admission_program_references",
        ["name"],
        unique=False,
    )
    op.create_table(
        "admission_program_outcomes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("program_reference_id", sa.UUID(), nullable=False),
        sa.Column("recruitment_period", sa.String(length=40), nullable=True),
        sa.Column("selection_type", sa.String(length=100), nullable=True),
        sa.Column("selection_name", sa.String(length=240), nullable=True),
        sa.Column("initial_recruitment_count", sa.Integer(), nullable=True),
        sa.Column("transferred_recruitment_count", sa.Integer(), nullable=True),
        sa.Column("final_recruitment_count", sa.Integer(), nullable=True),
        sa.Column("competition_rate", sa.Float(), nullable=True),
        sa.Column("additional_admission_count", sa.Integer(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["program_reference_id"], ["admission_program_references.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_admission_program_outcomes_program_reference_id"),
        "admission_program_outcomes",
        ["program_reference_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_admission_program_outcomes_program_reference_id"),
        table_name="admission_program_outcomes",
    )
    op.drop_table("admission_program_outcomes")
    op.drop_index(
        op.f("ix_admission_program_references_name"),
        table_name="admission_program_references",
    )
    op.drop_index(
        op.f("ix_admission_program_references_source_reference_code"),
        table_name="admission_program_references",
    )
    op.drop_index(
        op.f("ix_admission_program_references_source_admission_year"),
        table_name="admission_program_references",
    )
    op.drop_index(
        op.f("ix_admission_program_references_university_id"),
        table_name="admission_program_references",
    )
    op.drop_table("admission_program_references")
