"""Alembic's environment for the units store's migrations.

Online, it runs against `sqlalchemy.url` on an async engine, or on a connection a caller already
holds and passes as `config.attributes["connection"]` (so code inside an event loop can migrate
without starting another). Offline (`--sql`) it renders the statements for `sqlalchemy.url`'s
dialect."""

import asyncio

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from agent_build_kit.orchestration.sql.tables import METADATA

config = context.config


def database_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise ValueError(
            "sqlalchemy.url is not set: give the migrations a database URL, or a connection "
            "in config.attributes['connection']"
        )
    return url


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=METADATA)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(database_url())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


def run_offline() -> None:
    context.configure(url=database_url(), target_metadata=METADATA, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_offline()
elif (held := config.attributes.get("connection")) is not None:
    run_migrations(held)
else:
    asyncio.run(run_online())
