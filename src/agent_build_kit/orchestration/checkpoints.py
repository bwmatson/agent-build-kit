"""The Checkpoints interface: where a unit graph's thread lives between ticks.

An implementation opens a LangGraph checkpoint saver that deserialises only the types the
checkpointer allows (`graph.checkpointer.ALLOWED_MSGPACK_MODULES`).
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver

# The name the implementations register under in the deployment registry.
INTERFACE = "checkpoints"


class Checkpoints(Protocol):
    def open(self) -> AbstractAsyncContextManager[BaseCheckpointSaver]:
        """The saver over the installation's unit graphs, open for the context's duration."""
        raise NotImplementedError
