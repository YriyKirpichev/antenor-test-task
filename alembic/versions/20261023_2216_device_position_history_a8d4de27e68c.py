"""device_position_history

Revision ID: a8d4de27e68c
Revises: 722fd080fc95
Create Date: 2026-10-23 22:16:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "a8d4de27e68c"
down_revision: Union[str, Sequence[str], None] = "722fd080fc95"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE device_positions (
            device_id   bigint           NOT NULL,
            lat         double precision NOT NULL,
            lon         double precision NOT NULL,
            recorded_at timestamptz      NOT NULL,
            ingested_at timestamptz      NOT NULL DEFAULT now()
        ) PARTITION BY RANGE (recorded_at)
        """
    )

    op.execute(
        """
        CREATE INDEX ix_device_positions_device_recorded_at
        ON device_positions (device_id, recorded_at DESC)
        """
    )

    op.execute(
        "CREATE TABLE device_positions_default "
        "PARTITION OF device_positions DEFAULT"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE device_positions")
