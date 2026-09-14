"""cache writing requirement source document inspection metadata

Revision ID: b7d9e3a4f4d2
Revises: a3c0db7c7c71
Create Date: 2026-09-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7d9e3a4f4d2"
down_revision: Union[str, Sequence[str], None] = "a3c0db7c7c71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admission_writing_source_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("university_id", sa.UUID(), nullable=False),
        sa.Column("source_admission_year", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("inspection_status", sa.String(length=20), nullable=False),
        sa.Column("has_writing_marker", sa.Boolean(), nullable=True),
        sa.Column("marker_count", sa.Integer(), nullable=True),
        sa.Column("inspection_note", sa.Text(), nullable=True),
        sa.Column("inspected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["university_id"], ["universities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("university_id", "source_admission_year", name="uq_writing_source_university_year"),
    )
    op.create_index(
        op.f("ix_admission_writing_source_documents_university_id"),
        "admission_writing_source_documents",
        ["university_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_admission_writing_source_documents_university_id"),
        table_name="admission_writing_source_documents",
    )
    op.drop_table("admission_writing_source_documents")
