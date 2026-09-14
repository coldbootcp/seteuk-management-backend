"""add application preparation design tables

Revision ID: 5d6f01ce4aa8
Revises: 2eb77d972061
Create Date: 2026-09-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5d6f01ce4aa8"
down_revision: Union[str, Sequence[str], None] = "2eb77d972061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "application_preparations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("university_id", sa.UUID(), nullable=False),
        sa.Column("program_id", sa.UUID(), nullable=False),
        sa.Column("track_id", sa.UUID(), nullable=True),
        sa.Column("admission_year", sa.Integer(), nullable=False),
        sa.Column("central_question", sa.Text(), nullable=True),
        sa.Column("narrative_outline", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["program_id"], ["admission_programs.id"]),
        sa.ForeignKeyConstraint(["track_id"], ["admission_tracks.id"]),
        sa.ForeignKeyConstraint(["university_id"], ["universities.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_application_preparations_user_id"), "application_preparations", ["user_id"])
    op.create_table(
        "application_evidences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("preparation_id", sa.UUID(), nullable=False),
        sa.Column("activity_id", sa.UUID(), nullable=False),
        sa.Column("narrative_role", sa.String(length=40), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("student_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["preparation_id"], ["application_preparations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("preparation_id", "activity_id", name="uq_application_evidence_activity"),
    )
    op.create_index(op.f("ix_application_evidences_preparation_id"), "application_evidences", ["preparation_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_application_evidences_preparation_id"), table_name="application_evidences")
    op.drop_table("application_evidences")
    op.drop_index(op.f("ix_application_preparations_user_id"), table_name="application_preparations")
    op.drop_table("application_preparations")
