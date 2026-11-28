"""The PostgreSQL checkpoint saver on a real server.

The saver is opened over the test database `tests.support.postgres_url` reads from
`ABK_TEST_STORE_*`, in a schema of the test's own, through the same helper the units store's
e2e suite uses. The cases are the ones the SQLite saver passes: put, get, list by thread, writes
and delete by thread. It is marked e2e-test and excluded from the default suite.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from sqlalchemy.engine import make_url

from agent_build_kit.orchestration.sql.checkpoints import open_postgres_checkpointer
from tests.graph.checkpoint_reads import a_config

pytestmark = pytest.mark.e2e


@pytest.fixture
def saver_url(server: str, schema: str) -> str:
    """The test database's URL with the connection's search path in the test's schema."""
    return (
        make_url(server)
        .update_query_dict({"options": f"-c search_path={schema}"})
        .render_as_string(hide_password=False)
    )


def test_a_checkpoint_put_is_read_back(saver_url: str) -> None:
    checkpoint = empty_checkpoint()

    async def run() -> Any:
        async with open_postgres_checkpointer(saver_url) as saver:
            await saver.aput(a_config("feature/1"), checkpoint, {"source": "input", "step": 0}, {})
            return await saver.aget_tuple(a_config("feature/1"))

    found = asyncio.run(run())

    assert found is not None
    assert found.checkpoint["id"] == checkpoint["id"]


def test_a_threads_checkpoints_are_listed_newest_first_and_only_that_threads(
    saver_url: str,
) -> None:
    first, second = empty_checkpoint(), empty_checkpoint()

    async def run() -> list[str]:
        async with open_postgres_checkpointer(saver_url) as saver:
            config = await saver.aput(
                a_config("feature/1"), first, {"source": "input", "step": 0}, {}
            )
            await saver.aput(config, second, {"source": "loop", "step": 1}, {})
            await saver.aput(a_config("feature/2"), empty_checkpoint(), {}, {})
            return [c.checkpoint["id"] async for c in saver.alist(a_config("feature/1"))]

    assert asyncio.run(run()) == [second["id"], first["id"]]


def test_pending_writes_are_stored_with_their_checkpoint(saver_url: str) -> None:
    async def run() -> Any:
        async with open_postgres_checkpointer(saver_url) as saver:
            config = await saver.aput(
                a_config("feature/1"), empty_checkpoint(), {"source": "input", "step": 0}, {}
            )
            await saver.aput_writes(config, [("node", "value")], "task-1")
            return await saver.aget_tuple(config)

    found = asyncio.run(run())

    assert found is not None
    assert found.pending_writes == [("task-1", "node", "value")]


def test_deleting_a_thread_removes_its_checkpoints_and_writes_and_no_others(
    saver_url: str,
) -> None:
    async def run() -> tuple[Any, Any]:
        async with open_postgres_checkpointer(saver_url) as saver:
            for thread in ("feature/1", "feature/2"):
                config = await saver.aput(
                    a_config(thread), empty_checkpoint(), {"source": "input", "step": 0}, {}
                )
                await saver.aput_writes(config, [("node", "value")], "task-1")
            await saver.adelete_thread("feature/1")
            return (
                await saver.aget_tuple(a_config("feature/1")),
                await saver.aget_tuple(a_config("feature/2")),
            )

    deleted, kept = asyncio.run(run())

    assert deleted is None
    assert kept is not None
    assert kept.pending_writes == [("task-1", "node", "value")]


def test_a_checkpoint_written_by_one_open_is_read_by_the_next(saver_url: str) -> None:
    checkpoint = empty_checkpoint()

    async def write() -> None:
        async with open_postgres_checkpointer(saver_url) as saver:
            await saver.aput(a_config("feature/1"), checkpoint, {"source": "input", "step": 0}, {})

    async def read() -> Any:
        async with open_postgres_checkpointer(saver_url) as saver:
            return await saver.aget_tuple(a_config("feature/1"))

    asyncio.run(write())
    found = asyncio.run(read())

    assert found is not None
    assert found.checkpoint["id"] == checkpoint["id"]
