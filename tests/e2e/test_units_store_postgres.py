"""The units store's conformance suite on a real PostgreSQL server.

The server is the test database `tests.support.postgres_url` reads from `ABK_TEST_STORE_*`. Each
test works in a schema of its own in that database, migrated to the head revision through
Alembic and dropped afterwards, so tests share no tables under any worker count. It is marked
e2e-test and excluded from the default suite.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Connection, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from agent_build_kit.orchestration.sql.migrate import alembic_config, head_revision
from agent_build_kit.orchestration.sql.store import SqlUnitsStore
from agent_build_kit.orchestration.sql.tables import UNITS
from tests.support.postgres_url import postgres_url
from tests.support.units_store_conformance import CASES, Harness, run_case

pytestmark = pytest.mark.e2e


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


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_postgres_store_passes_the_conformance_case(
    case: str, server: str, schema: str
) -> None:
    def factory() -> Harness:
        engine = schema_engine(server, schema)
        # No pooled connection outlives the loop that opened it: each write runs on its own loop.
        side = schema_engine(server, schema, poolclass=NullPool)

        def write_behind(unit_id: str, body: dict[str, Any], version: int) -> None:
            async def write() -> None:
                async with side.begin() as connection:
                    await connection.execute(
                        update(UNITS)
                        .where(UNITS.c.id == unit_id)
                        .values(body=body, version=version + 1)
                    )

            # The case is running in an event loop, so the second writer runs on a thread of its
            # own, with a loop of its own, and is waited for (its error re-raised here).
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(asyncio.run, write()).result()

        async def close() -> None:
            await engine.dispose()
            await side.dispose()

        return Harness(store=SqlUnitsStore(engine), write_behind=write_behind, close=close)

    run_case(case, factory)


def test_a_second_client_with_the_same_settings_reads_the_unit_the_first_wrote(
    server: str, schema: str
) -> None:
    async def scenario() -> None:
        first = schema_engine(server, schema)
        second = schema_engine(server, schema)
        try:
            written = await SqlUnitsStore(first).put_if("feature/1", {"state": "planned"}, 0)
            updated = await SqlUnitsStore(first).put_if("feature/1", {"state": "built"}, 1)

            read = await SqlUnitsStore(second).get("feature/1")

            assert written.version == 1
            assert read == updated
            assert updated.version == 2
        finally:
            await first.dispose()
            await second.dispose()

    asyncio.run(scenario())


def test_the_migrated_schema_is_at_the_head_revision(server: str, schema: str) -> None:
    async def revision() -> str | None:
        engine = schema_engine(server, schema)
        try:
            async with engine.connect() as connection:
                found = await connection.execute(text("SELECT version_num FROM alembic_version"))
                return found.scalar_one()
        finally:
            await engine.dispose()

    assert asyncio.run(revision()) == head_revision()
