from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.ais import AISBase
from app.config import settings
from app.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url.replace("+asyncpg", "+psycopg"))
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = [Base.metadata, AISBase.metadata]


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url.replace("+asyncpg", "+psycopg"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema="balancer",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = settings.database_url.replace("+asyncpg", "+psycopg")
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema="balancer",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
