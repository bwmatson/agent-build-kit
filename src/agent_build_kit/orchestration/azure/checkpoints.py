"""The Azure Checkpoints implementation: LangGraph's PostgreSQL saver with a fresh Entra token
as the password of every new connection."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.base import BaseCheckpointSaver

if TYPE_CHECKING:
    from agent_build_kit.installation import Installation

# The scope an Entra token for Azure Database for PostgreSQL is requested for.
TOKEN_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


def token_connection_kwargs(host: str, credential: Any) -> Callable[[], dict[str, Any]]:
    """A callable returning the keyword arguments of a new connection to `host`, its password a
    token obtained from `credential` on that call."""
    raise NotImplementedError


class AzureCheckpoints:
    def __init__(self, connection_kwargs: Callable[[], dict[str, Any]]) -> None:
        """`connection_kwargs()` is called once for each new connection the pool opens."""
        raise NotImplementedError

    def open(self) -> AbstractAsyncContextManager[BaseCheckpointSaver]:
        raise NotImplementedError


def build_checkpoints(
    installation: Installation,
    *,
    make_credential: Callable[[str | None], Any] | None = None,
) -> AzureCheckpoints:
    """Checkpoints for an `azure` installation; `make_credential(client_id)` builds the
    managed-identity credential and defaults to the real one."""
    raise NotImplementedError
