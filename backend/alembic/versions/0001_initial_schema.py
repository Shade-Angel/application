"""Initial balancer schema."""

import sqlalchemy as sa

from alembic import op
from app.ais import AISBase
from app.models import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _initial_balancer_metadata() -> sa.MetaData:
    """Freeze the base revision: later-only objects belong to revision 0002."""
    metadata = sa.MetaData(schema="balancer")
    later_tables = {"executor_daily_usage", "candidate_decisions"}
    for source in Base.metadata.sorted_tables:
        if source.name in later_tables:
            continue
        table = source.to_metadata(metadata)
        if source.name == "orders":
            table._columns.remove(table.c.rejection_reason)
        if source.name == "outbox":
            table._columns.remove(table.c.retry_at)
            table._columns.remove(table.c.last_error)
    return metadata


def _initial_ais_metadata() -> sa.MetaData:
    """Keep the normalized settings table in the additive revision 0002."""
    metadata = sa.MetaData(schema="ais")
    for source in AISBase.metadata.sorted_tables:
        if source.name != "ais_user_settings":
            table = source.to_metadata(metadata)
            if source.name == "ais_orders":
                table._columns.remove(table.c.weight)
            elif source.name == "ais_assignments":
                table.c.id.identity = None
    return metadata


def upgrade() -> None:
    _initial_balancer_metadata().create_all(bind=op.get_bind())
    _initial_ais_metadata().create_all(bind=op.get_bind())


def downgrade() -> None:
    _initial_ais_metadata().drop_all(bind=op.get_bind())
    _initial_balancer_metadata().drop_all(bind=op.get_bind())
