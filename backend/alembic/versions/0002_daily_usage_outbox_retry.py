"""Track daily usage per date and store outbox retry backoff metadata."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002_daily_usage_outbox_retry"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("rejection_reason", sa.String(length=255), nullable=True),
        schema="balancer",
    )
    op.create_table(
        "ais_user_settings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("min_accept_sum", sa.BigInteger(), nullable=True),
        sa.Column("max_accept_sum", sa.BigInteger(), nullable=True),
        sa.Column("min_reject_sum", sa.BigInteger(), nullable=True),
        sa.Column("max_reject_sum", sa.BigInteger(), nullable=True),
        sa.Column("client_msp", sa.String(length=255), nullable=True),
        sa.Column("executor_msp", sa.String(length=255), nullable=True),
        sa.Column("order_type", sa.String(length=64), nullable=True),
        sa.Column("subject", sa.String(length=128), nullable=True),
        sa.Column("vip", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("max_daily_limit", sa.SmallInteger(), nullable=True),
        sa.Column(
            "extra_settings",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["ais.ais_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_ais_user_settings_user_id"),
        schema="ais",
    )
    op.add_column(
        "outbox",
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True),
        schema="balancer",
    )
    op.add_column("outbox", sa.Column("last_error", sa.Text(), nullable=True), schema="balancer")
    op.create_table(
        "executor_daily_usage",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("executor_id", sa.BigInteger(), nullable=False),
        sa.Column("day_date", sa.Date(), nullable=False),
        sa.Column("assigned_count", sa.Integer(), nullable=False),
        sa.Column("assigned_weight", sa.Numeric(12, 3), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("executor_id", "day_date"),
        schema="balancer",
    )
    op.create_index(
        "ix_balancer_executor_daily_usage_executor_id",
        "executor_daily_usage",
        ["executor_id"],
        schema="balancer",
    )
    op.create_index(
        "ix_balancer_executor_daily_usage_day_date",
        "executor_daily_usage",
        ["day_date"],
        schema="balancer",
    )
    op.execute(
        """
        INSERT INTO balancer.executor_daily_usage
            (executor_id, day_date, assigned_count, assigned_weight)
        SELECT id, day_date, day_count, day_weight
        FROM balancer.executors
        ON CONFLICT (executor_id, day_date) DO NOTHING
        """
    )
    op.create_table(
        "candidate_decisions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("executor_id", sa.BigInteger(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("score", sa.Numeric(14, 6), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="balancer",
    )
    op.create_index(
        "ix_balancer_candidate_decisions_order_id",
        "candidate_decisions",
        ["order_id"],
        schema="balancer",
    )
    op.create_index(
        "ix_balancer_candidate_decisions_executor_id",
        "candidate_decisions",
        ["executor_id"],
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_table("ais_user_settings", schema="ais")
    op.drop_index(
        "ix_balancer_candidate_decisions_order_id",
        table_name="candidate_decisions",
        schema="balancer",
    )
    op.drop_index(
        "ix_balancer_candidate_decisions_executor_id",
        table_name="candidate_decisions",
        schema="balancer",
    )
    op.drop_table("candidate_decisions", schema="balancer")
    op.drop_index(
        "ix_balancer_executor_daily_usage_day_date",
        table_name="executor_daily_usage",
        schema="balancer",
    )
    op.drop_index(
        "ix_balancer_executor_daily_usage_executor_id",
        table_name="executor_daily_usage",
        schema="balancer",
    )
    op.drop_table("executor_daily_usage", schema="balancer")
    op.drop_column("outbox", "last_error", schema="balancer")
    op.drop_column("outbox", "retry_at", schema="balancer")
    op.drop_column("orders", "rejection_reason", schema="balancer")
