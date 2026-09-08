"""merge latest consultation and admissions catalog migration heads

Revision ID: f6a9c3d5e702
Revises: a4d0ac2855b5, e5a9c2d8f306
Create Date: 2026-09-08
"""

from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f6a9c3d5e702"
down_revision: tuple[str, str] = ("a4d0ac2855b5", "e5a9c2d8f306")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # This revision only joins two already-applied, independent migration paths.
    pass


def downgrade() -> None:
    # Splitting the migration graph does not alter database schema.
    pass
