"""The local Checkpoints implementation: today's SQLite saver over the unit graphs file."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

from langgraph.checkpoint.base import BaseCheckpointSaver

if TYPE_CHECKING:
    from agent_build_kit.installation import Installation


class LocalCheckpoints:
    def __init__(self, installation: Installation) -> None:
        self.installation = installation

    def open(self) -> AbstractAsyncContextManager[BaseCheckpointSaver]:
        raise NotImplementedError
