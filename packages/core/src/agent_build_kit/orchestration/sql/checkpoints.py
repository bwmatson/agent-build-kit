"""The PostgreSQL checkpoint saver: LangGraph's saver tables in the store's database."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from urllib.parse import quote, urlencode

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.engine import make_url

from agent_build_kit.graph.checkpointer import allowlisted_serde


def psycopg_url(url: str) -> str:
    """`url` as psycopg reads it: the store's URL without the `+asyncpg` driver."""
    parsed = make_url(url)
    # SQLAlchemy writes a space in a query value as `+`, which libpq reads literally (an
    # `options=-c search_path=x` would reach the server as `-c+search_path=x`): write `%20`.
    plain = parsed.set(drivername=parsed.drivername.split("+", 1)[0], query={})
    query = urlencode(
        [(k, v) for k, values in parsed.query.items() for v in _each(values)], quote_via=quote
    )
    base = plain.render_as_string(hide_password=False)
    return f"{base}?{query}" if query else base


def _each(value: str | tuple[str, ...]) -> tuple[str, ...]:
    return (value,) if isinstance(value, str) else value


@asynccontextmanager
async def _open(url: str) -> AsyncIterator[BaseCheckpointSaver]:
    async with AsyncPostgresSaver.from_conn_string(
        psycopg_url(url), serde=allowlisted_serde()
    ) as saver:
        await saver.setup()
        yield saver


def open_postgres_checkpointer(url: str) -> AbstractAsyncContextManager[BaseCheckpointSaver]:
    """The PostgreSQL saver over the store database at `url`, deserialising only the
    allowlisted types, its tables created on first use. Every open runs the saver's setup, so
    `abk serve`'s reads do too, and need a role that may create the saver's tables."""
    return _open(url)
