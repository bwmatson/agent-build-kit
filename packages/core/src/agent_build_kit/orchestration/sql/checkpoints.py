"""The PostgreSQL checkpoint saver: LangGraph's saver tables in the store's database."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.engine import make_url

from agent_build_kit.graph.checkpointer import allowlisted_serde


def psycopg_url(url: str) -> str:
    """`url` as psycopg reads it: the store's URL without the `+asyncpg` driver."""
    parsed = make_url(url)
    plain = parsed.set(drivername=parsed.drivername.split("+", 1)[0])
    return plain.render_as_string(hide_password=False)


@asynccontextmanager
async def _open(url: str) -> AsyncIterator[BaseCheckpointSaver]:
    async with AsyncPostgresSaver.from_conn_string(
        psycopg_url(url), serde=allowlisted_serde()
    ) as saver:
        await saver.setup()
        yield saver


def open_postgres_checkpointer(url: str) -> AbstractAsyncContextManager[BaseCheckpointSaver]:
    """The PostgreSQL saver over the store database at `url`, deserialising only the
    allowlisted types, its tables created on first use."""
    return _open(url)
