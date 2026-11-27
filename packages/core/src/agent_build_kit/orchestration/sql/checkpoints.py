"""The PostgreSQL checkpoint saver: LangGraph's saver tables in the store's database."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager

from langgraph.checkpoint.base import BaseCheckpointSaver


def open_postgres_checkpointer(url: str) -> AbstractAsyncContextManager[BaseCheckpointSaver]:
    """The PostgreSQL saver over the store database at `url`, deserialising only the
    allowlisted types."""
    raise NotImplementedError
