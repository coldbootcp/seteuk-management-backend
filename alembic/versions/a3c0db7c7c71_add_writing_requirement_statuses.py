"""add explicit writing requirement verification statuses

Revision ID: a3c0db7c7c71
Revises: 9d3a6b42f551
Create Date: 2026-09-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3c0db7c7c71"
down_revision: Union[str, Sequence[str], None] = "9d3a6b42f551"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admission_writing_requirement_statuses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("track_id", sa.UUID(), nullable=False),
        sa.Column("requirement_status", sa.String(length=20), nullable=False),
        sa.Column("source_admission_year", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_status", sa.String(length=20), nullable=True),
        sa.Column("verification_note", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["track_id"], ["admission_tracks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("track_id"),
    )
    op.create_index(
        op.f("ix_admission_writing_requirement_statuses_track_id"),
        "admission_writing_requirement_statuses",
        ["track_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_admission_writing_requirement_statuses_track_id"),
        table_name="admission_writing_requirement_statuses",
    )
    op.drop_table("admission_writing_requirement_statuses")
