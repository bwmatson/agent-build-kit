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
        """The SQLite saver over the unit graphs file, an older database carried over first."""
        return open_unit_graphs(self.installation)
