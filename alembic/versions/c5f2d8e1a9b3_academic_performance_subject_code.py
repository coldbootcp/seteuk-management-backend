"""academic_performance subject_code

과목 카탈로그(app/services/subject_catalog.py)와 과목 기록을 1:1로 잇는 코드. 학생이
후보에서 고른 과목만 채워지고, 생기부 파싱 행과 "기타"로 직접 입력한 과목은 비어 있다.

Revision ID: c5f2d8e1a9b3
Revises: b3e7a1c9d24f
Create Date: 2026-09-27 23:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5f2d8e1a9b3"
down_revision: str | Sequence[str] | None = "b3e7a1c9d24f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "academic_performance",
        sa.Column("subject_code", sa.String(length=60), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("academic_performance", "subject_code")
