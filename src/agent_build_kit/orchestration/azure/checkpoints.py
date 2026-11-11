"""The Azure Checkpoints implementation: LangGraph's PostgreSQL saver with a fresh Entra token
as the password of every new connection."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from agent_build_kit import orchestration
from agent_build_kit.graph.checkpointer import ALLOWED_MSGPACK_MODULES

if TYPE_CHECKING:
    from agent_build_kit.installation import Installation

# The scope an Entra token for Azure Database for PostgreSQL is requested for.
TOKEN_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


def token_connection_kwargs(host: str, credential: Any) -> Callable[[], dict[str, Any]]:
    """A callable returning the keyword arguments of a new connection to `host`, its password a
    token obtained from `credential` on that call."""

    def kwargs() -> dict[str, Any]:
        return dict(
            host=host,
            password=credential.get_token(TOKEN_SCOPE).token,
            sslmode="require",
        )

    return kwargs


class AzureCheckpoints:
    def __init__(self, connection_kwargs: Callable[[], dict[str, Any]]) -> None:
        """`connection_kwargs()` is called once for each new connection the pool opens."""
        self._connection_kwargs = connection_kwargs

    def open(self) -> AbstractAsyncContextManager[BaseCheckpointSaver]:
        return self._open()

    @asynccontextmanager
    async def _open(self) -> AsyncIterator[BaseCheckpointSaver]:
        postgres = orchestration.import_sdk("azure", "langgraph.checkpoint.postgres.aio")
        pool_module = orchestration.import_sdk("azure", "psycopg_pool")
        conninfo = orchestration.import_sdk("azure", "psycopg.conninfo")
        rows = orchestration.import_sdk("azure", "psycopg.rows")

        def new_connection_kwargs() -> dict[str, Any]:
            # Called by the pool for each connection it opens, so each takes a new password.
            given = dict(self._connection_kwargs())
            merged = conninfo.conninfo_to_dict(given.pop("conninfo", ""))
            merged.update(given)
            merged.update(autocommit=True, prepare_threshold=0, row_factory=rows.dict_row)
            return merged

        async with pool_module.AsyncConnectionPool(
            "", kwargs=new_connection_kwargs, open=False
        ) as pool:
            serde = JsonPlusSerializer(allowed_msgpack_modules=list(ALLOWED_MSGPACK_MODULES))
            saver = postgres.AsyncPostgresSaver(pool, serde=serde)
            await saver.setup()
            yield saver


def _default_credential(client_id: str | None) -> Any:
    identity = orchestration.import_sdk("azure", "azure.identity")
    return identity.ManagedIdentityCredential(client_id=client_id)


def build_checkpoints(
    installation: Installation,
    *,
    make_credential: Callable[[str | None], Any] | None = None,
) -> AzureCheckpoints:
    """Checkpoints for an `azure` installation; `make_credential(client_id)` builds the
    managed-identity credential and defaults to the real one."""
    settings = installation.config.deployment.azure
    if not settings.database_host:
        raise orchestration.Refused(
            "deployment.azure.database_host is not set: Azure checkpoints need a database host"
        )
    credential = (make_credential or _default_credential)(settings.identity_client_id)
    return AzureCheckpoints(token_connection_kwargs(settings.database_host, credential))
