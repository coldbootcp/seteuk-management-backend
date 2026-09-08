"""add source program code to admission catalog

Revision ID: 2eb77d972061
Revises: 8cb274a175f9
Create Date: 2026-09-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2eb77d972061"
down_revision: Union[str, Sequence[str], None] = "8cb274a175f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "admission_programs", sa.Column("source_program_code", sa.String(length=32), nullable=True)
    )
    op.create_index(
        op.f("ix_admission_programs_source_program_code"),
        "admission_programs",
        ["source_program_code"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_admission_programs_source_program_code"), table_name="admission_programs")
    op.drop_column("admission_programs", "source_program_code")
