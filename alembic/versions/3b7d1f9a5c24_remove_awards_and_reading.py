"""remove awards and reading activities

Revision ID: 3b7d1f9a5c24
Revises: 4c8e2a7d9b13
Create Date: 2026-09-29

수상경력과 독서활동상황은 대입 평가에 반영하지 않으므로 서비스에서 없앤다(소유자 결정).
awards·reading_activities 테이블과 계획의 독서 승격 열을 지운다. 이미 쌓인 행은 복구되지
않는다 — downgrade는 빈 테이블만 되살린다. 계획 유형 reading·award는 더 이상 없어서
other로 옮긴다(계획 자체는 남긴다).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "3b7d1f9a5c24"
down_revision: str | None = "4c8e2a7d9b13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE plan_items SET item_type = 'other' WHERE item_type IN ('reading', 'award')")
    op.drop_column("plan_items", "completed_reading_id")
    op.drop_table("reading_activities")
    op.drop_table("awards")


def downgrade() -> None:
    op.create_table(
        "awards",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_upload_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("seteuk_uploads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("grade", sa.Integer(), nullable=True),
        sa.Column("semester", sa.Integer(), nullable=True),
        sa.Column("participants", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("rank", sa.String(100), nullable=True),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("raw_date", sa.String(50), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_awards_user_id", "awards", ["user_id"])
    op.create_index("ix_awards_source_upload_id", "awards", ["source_upload_id"])
    op.create_table(
        "reading_activities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_upload_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("seteuk_uploads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("grade", sa.Integer(), nullable=False),
        sa.Column("semester", sa.Integer(), nullable=True),
        sa.Column("subject", sa.String(100), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("author", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_reading_activities_user_id", "reading_activities", ["user_id"])
    op.create_index(
        "ix_reading_activities_source_upload_id", "reading_activities", ["source_upload_id"]
    )
    op.add_column(
        "plan_items",
        sa.Column(
            "completed_reading_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reading_activities.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
