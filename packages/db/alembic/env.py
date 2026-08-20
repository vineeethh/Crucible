"""Alembic environment. DATABASE_URL (if set) overrides alembic.ini's URL.

Migrations use a synchronous psycopg connection even though the app uses an
async engine — migration runs are an explicit, observable deployment step.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from crucible.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if url_override := os.environ.get("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", url_override)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Render SQL without a live database (used by CI's offline check)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
