"""Alembic's environment: runs the migrations against `sqlalchemy.url` on an async engine."""

import asyncio

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from agent_build_kit.orchestration.sql.tables import METADATA

config = context.config


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=METADATA)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(config.get_main_option("sqlalchemy.url") or "")
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


asyncio.run(run_online())
