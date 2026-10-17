"""Alembic environment for the Overture SQLite database.

The URL comes from the application's configuration so that migrations always
target the same file the app opens, and SQLModel's
metadata drives autogenerate so a model change and its migration cannot
describe different schemas.
"""

lazy import asyncio
lazy import logging

lazy from alembic import context
lazy from sqlalchemy import pool
lazy from sqlalchemy.engine import Connection
lazy from sqlalchemy.ext.asyncio import async_engine_from_config

lazy from overture.config import RuntimeSettings, load_configuration
lazy from overture.db import metadata
lazy from overture.runtime_paths import database_url

config = context.config
# The application passes its own connection and owns logging; the standalone
# ``alembic`` command opens the configured database and logs to stderr.
if "connection" not in config.attributes:
    runtime_settings = load_configuration(RuntimeSettings)
    config.set_main_option(
        "sqlalchemy.url", database_url(runtime_settings.OVERTURE_CONFIG_DIR)
    )
    logging.basicConfig(format="%(levelname)-5.5s [%(name)s] %(message)s")
    logging.getLogger("alembic").setLevel(logging.INFO)

target_metadata = metadata


def _configure(connection: Connection) -> None:
    """Configure a live connection, including how autogenerate compares."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite cannot ALTER most things in place; batch mode rewrites the
        # table instead, which is what makes column changes possible at all.
        render_as_batch=True,
        compare_type=True,
        compare_server_default=True,
    )


def run_migrations_offline() -> None:
    """Emit SQL for the configured URL without connecting."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Open a connection of our own and run migrations on it."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
elif (existing := config.attributes.get("connection")) is not None:
    # The app runs migrations at startup on a connection it already holds,
    # inside a running event loop. Reuse it rather than opening a second one.
    _run(existing)
else:
    asyncio.run(run_migrations_online())
