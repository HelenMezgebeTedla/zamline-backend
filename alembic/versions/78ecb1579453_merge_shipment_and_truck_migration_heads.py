"""merge shipment and truck migration heads

Revision ID: 78ecb1579453
Revises: 2d90d6a9ae20, 97b5a09707fe
Create Date: 2026-10-24 14:09:01.777872

"""
from typing import Sequence, Union



# revision identifiers, used by Alembic.
revision: str = '78ecb1579453'
down_revision: Union[str, Sequence[str], None] = ('2d90d6a9ae20', '97b5a09707fe')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
