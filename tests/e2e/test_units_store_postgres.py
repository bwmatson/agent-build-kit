"""The units store's conformance suite on a real PostgreSQL server.

The server is the test database `tests.support.postgres_url` reads from `ABK_TEST_STORE_*`. Each
test works in a schema of its own in that database, migrated to the head revision through
Alembic and dropped afterwards, so tests share no tables under any worker count. It is marked
e2e-test and excluded from the default suite.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import text, update
from sqlalchemy.pool import NullPool

from agent_build_kit.orchestration.sql.migrate import head_revision
from agent_build_kit.orchestration.sql.store import SqlUnitsStore
from agent_build_kit.orchestration.sql.tables import UNITS
from tests.support.postgres_store import schema_engine
from tests.support.units_store_conformance import CASES, Harness, run_case

pytestmark = pytest.mark.e2e


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
