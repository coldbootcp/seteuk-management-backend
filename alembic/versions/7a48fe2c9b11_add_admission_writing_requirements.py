"""add admission writing requirements

Revision ID: 7a48fe2c9b11
Revises: 5d6f01ce4aa8
Create Date: 2026-09-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7a48fe2c9b11"
down_revision: Union[str, Sequence[str], None] = "5d6f01ce4aa8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admission_writing_requirements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("track_id", sa.UUID(), nullable=False),
        sa.Column("prompt_order", sa.Integer(), nullable=False),
        sa.Column("prompt_label", sa.String(length=160), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("min_characters", sa.Integer(), nullable=True),
        sa.Column("max_characters", sa.Integer(), nullable=True),
        sa.Column("character_unit", sa.String(length=30), nullable=False),
        sa.Column("submission_method", sa.String(length=160), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_status", sa.String(length=20), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["track_id"], ["admission_tracks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_admission_writing_requirements_track_id"), "admission_writing_requirements", ["track_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_admission_writing_requirements_track_id"), table_name="admission_writing_requirements")
    op.drop_table("admission_writing_requirements")
