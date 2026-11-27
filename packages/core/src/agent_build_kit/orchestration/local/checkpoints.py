"""The local Checkpoints implementation: today's SQLite saver over the unit graphs file."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

from langgraph.checkpoint.base import BaseCheckpointSaver

from agent_build_kit.graph.checkpointer import open_unit_graphs
from agent_build_kit.orchestration.sql.checkpoints import open_postgres_checkpointer

if TYPE_CHECKING:
    from agent_build_kit.installation import Installation


class LocalCheckpoints:
    def __init__(
        self,
        installation: Installation,
        *,
        sqlite: Callable[[Installation], AbstractAsyncContextManager[BaseCheckpointSaver]] = (
            open_unit_graphs
        ),
        postgres: Callable[[str], AbstractAsyncContextManager[BaseCheckpointSaver]] = (
            open_postgres_checkpointer
        ),
    ) -> None:
        self.installation = installation
        self.sqlite = sqlite
        self.postgres = postgres

    def open(self) -> AbstractAsyncContextManager[BaseCheckpointSaver]:
        """The PostgreSQL saver over the store when `threads_in_store`, else the SQLite saver over
        the unit graphs file, an older database carried over first."""
        url = store_url_of(self.installation)
        if url:
            return self.postgres(url)
        return self.sqlite(self.installation)


def store_url_of(installation: Installation) -> str | None:
    """The store's database URL (`store.url`, or the one built from `store.host` and
    `store.database`), None when no store is configured."""
    # Not at module level: the configuration imports this package, and `url` the configuration.
    from agent_build_kit.orchestration.sql.url import store_url

    return store_url(installation.config.store)


def threads_in_store(installation: Installation) -> bool:
    """Whether the installation's unit threads live in the store's database, not the SQLite
    file: the one rule `LocalCheckpoints.open` and `abk serve`'s reads share."""
    return store_url_of(installation) is not None
