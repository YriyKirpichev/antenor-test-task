"""init

Revision ID: f59c9eee526f
Revises: 
Create Date: 2026-10-23 15:23:14.867006

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f59c9eee526f'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

def downgrade() -> None:
    return None
