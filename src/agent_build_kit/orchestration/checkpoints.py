"""The Checkpoints interface: where a unit graph's thread lives between ticks.

An implementation opens a LangGraph checkpoint saver that deserialises only the types the
checkpointer allows (`graph.checkpointer.ALLOWED_MSGPACK_MODULES`).
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver

from agent_build_kit import orchestration

if TYPE_CHECKING:
    from agent_build_kit.installation import Installation

# The name the implementations register under in the deployment registry.
INTERFACE = "checkpoints"


class Checkpoints(Protocol):
    def open(self) -> AbstractAsyncContextManager[BaseCheckpointSaver]:
        """The saver over the installation's unit graphs, open for the context's duration."""
        raise NotImplementedError


def open_checkpoints(
    installation: Installation,
) -> AbstractAsyncContextManager[BaseCheckpointSaver]:
    """The saver over the installation's unit graphs, from the deployment's implementation."""
    checkpoints: Checkpoints = orchestration.get(INTERFACE, installation)
    return checkpoints.open()
