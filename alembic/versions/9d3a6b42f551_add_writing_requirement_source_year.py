"""track the verified year of writing requirements

Revision ID: 9d3a6b42f551
Revises: 7a48fe2c9b11
Create Date: 2026-09-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9d3a6b42f551"
down_revision: Union[str, Sequence[str], None] = "7a48fe2c9b11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "admission_writing_requirements",
        sa.Column("source_admission_year", sa.Integer(), nullable=True),
    )
    op.execute("UPDATE admission_writing_requirements SET source_admission_year = 2027")
    op.alter_column("admission_writing_requirements", "source_admission_year", nullable=False)


def downgrade() -> None:
    op.drop_column("admission_writing_requirements", "source_admission_year")
