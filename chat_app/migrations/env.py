"""
Alembic environment configuration.

Reads the database URL from chat_app.settings (which resolves
DATABASE_URL / CHAINLIT_DB_CONNINFO env vars and config.yaml).
Supports both online (connected) and offline (SQL-script) migrations.
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# Alembic Config object — provides access to alembic.ini values.
config = context.config

# Set up Python logging from the ini file.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _get_url() -> str:
    """Resolve the sync database URL for migrations.

    Priority: ALEMBIC_DATABASE_URL env var > chat_app.settings > alembic.ini.
    The URL is normalised to a sync driver (psycopg2) because Alembic
    runs migrations synchronously.
    """
    url = os.getenv("ALEMBIC_DATABASE_URL", "")
    if not url:
        try:
            from chat_app.settings import get_settings
            url = get_settings().database.url
        except Exception:
            url = config.get_main_option("sqlalchemy.url", "")

    # Convert async drivers to sync for Alembic
    url = (
        url
        .replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg://", "postgresql://")
    )
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.
    """
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Creates a connection to the database and runs migrations.
    """
    url = _get_url()
    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
