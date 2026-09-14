"""add program reference collection checkpoints

Revision ID: e5a9c2d8f306
Revises: f1c3e9a8b702
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5a9c2d8f306"
down_revision: str | Sequence[str] | None = "f1c3e9a8b702"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "admission_program_references",
        sa.Column("outcomes_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "admission_program_references",
        sa.Column("profile_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    # 이미 수집한 서울 주요대학 데이터를 다시 긁지 않는다. 결과가 0건인 학과는
    # 아직 체크포인트가 없으므로 새 수집기가 한 번 확인한 뒤 기록한다.
    op.execute(
        """
        UPDATE admission_program_references
        SET profile_checked_at = verified_at
        WHERE detail_sections IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE admission_program_references AS reference
        SET outcomes_checked_at = source.verified_at
        FROM (
            SELECT program_reference_id, MAX(verified_at) AS verified_at
            FROM admission_program_outcomes
            GROUP BY program_reference_id
        ) AS source
        WHERE reference.id = source.program_reference_id
        """
    )


def downgrade() -> None:
    op.drop_column("admission_program_references", "profile_checked_at")
    op.drop_column("admission_program_references", "outcomes_checked_at")
