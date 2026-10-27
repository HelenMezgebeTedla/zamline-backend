"""add terms acceptance to users

Revision ID: c3f1a7d92e64
Revises: 78ecb1579453
Create Date: 2026-10-27 11:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c3f1a7d92e64"
down_revision: Union[str, Sequence[str], None] = "78ecb1579453"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users", sa.Column("terms_version", sa.String(length=20), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "terms_version")
    op.drop_column("users", "terms_accepted_at")
