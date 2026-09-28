"""Persist order weight in the AIS emulator so status updates retain it."""

import sqlalchemy as sa

from alembic import op

revision = "0003_ais_order_weight"
down_revision = "0002_daily_usage_outbox_retry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ais_orders",
        sa.Column("weight", sa.Numeric(8, 3), server_default="1.0", nullable=False),
        schema="ais",
    )


def downgrade() -> None:
    op.drop_column("ais_orders", "weight", schema="ais")
