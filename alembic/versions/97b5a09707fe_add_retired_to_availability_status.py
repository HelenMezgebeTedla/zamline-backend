"""add retired to availability status

Revision ID: 97b5a09707fe
Revises: 8dd6ce7658ec
Create Date: 2026-10-20 09:18:20.237230

"""

from typing import Sequence, Union

from alembic import op


revision: str = "97b5a09707fe"
down_revision: Union[str, Sequence[str], None] = "8dd6ce7658ec"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    exists = bind.exec_driver_sql(
        "SELECT 1 FROM pg_type WHERE typname = 'availabilitystatus'"
    ).scalar()
    if exists:
        with op.get_context().autocommit_block():
            op.execute(
                "ALTER TYPE availabilitystatus ADD VALUE IF NOT EXISTS 'retired'"
            )


def downgrade() -> None:
    pass
