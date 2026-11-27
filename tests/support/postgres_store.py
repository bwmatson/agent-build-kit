"""A schema of its own in the test PostgreSQL database the e2e cases write to.

The server is the one `tests.support.postgres_url` reads from `ABK_TEST_STORE_*`. Each test gets a
fresh schema, migrated to the head revision through Alembic and dropped afterwards, so tests share
no tables under any worker count. The fixtures `server` and `schema` are collected from
`tests/e2e/conftest.py`.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from agent_build_kit.orchestration.sql.migrate import alembic_config
from tests.support.postgres_url import postgres_url


def schema_engine(url: str, schema: str, **options: Any) -> AsyncEngine:
    """An engine whose connections resolve unqualified tables in `schema`."""
    return create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema}}, **options
    )


async def migrate(url: str, schema: str) -> None:
    engine = schema_engine(url, schema)
    try:
        async with engine.begin() as connection:
            config = alembic_config("")

            def upgrade(held: Connection) -> None:
                config.attributes["connection"] = held
                command.upgrade(config, "head")

            await connection.run_sync(upgrade)
    finally:
        await engine.dispose()


async def create_schema(url: str, schema: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    finally:
        await engine.dispose()


async def drop_schema(url: str, schema: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    finally:
        await engine.dispose()


@pytest.fixture
def server() -> str:
    return postgres_url()


@pytest.fixture
def schema(server: str) -> Iterator[str]:
    """A fresh schema of the test database, migrated to head, dropped when the test is done."""
    name = f"abk_test_{uuid.uuid4().hex}"
    asyncio.run(create_schema(server, name))
    asyncio.run(migrate(server, name))
    try:
        yield name
    finally:
        asyncio.run(drop_schema(server, name))
