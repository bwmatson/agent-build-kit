"""The Azure Artifacts implementation: each key is a blob in the installation's container."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from agent_build_kit import orchestration
from agent_build_kit.installation import Installation
from agent_build_kit.orchestration.artifacts import ArtifactWriter, MissingArtifact
from agent_build_kit.redaction import redact_text

# The most bytes one append call carries; a larger flush is split into several calls.
DEFAULT_BLOCK_SIZE = 4 * 1024 * 1024

# The container that holds an installation's artifacts, in the deployment's storage account.
CONTAINER_NAME = "artifacts"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _is_missing(error: Exception) -> bool:
    """Whether `error` is the SDK's not-found error (matched by name, so the SDK stays lazy)."""
    return type(error).__name__ == "ResourceNotFoundError"


class _BlockWriter:
    """Buffers text and appends it to an append blob, in blocks no larger than `block_size`.

    The append blob is created when the writer opens, so the key reads as empty from then on,
    as a freshly opened local file does; one that is already there is kept and appended to. A
    key first stored by `put` is a block blob, which cannot be appended to: a log that grows is
    written only through a writer.
    """

    def __init__(self, container: Any, key: str, block_size: int) -> None:
        self._blob = container.get_blob_client(key)
        self._key = key
        self._block_size = block_size
        self._buffer: list[str] = []
        core = orchestration.import_sdk("azure", "azure.core")
        try:
            # One conditional request, so a second writer never replaces what the first appended.
            self._blob.create_append_blob(match_condition=core.MatchConditions.IfMissing)
        except Exception as error:
            if type(error).__name__ != "ResourceExistsError":
                raise

    def write(self, text: str) -> None:
        self._buffer.append(redact_text(text, where=self._key))

    def flush(self) -> None:
        if not self._buffer:
            return
        data = "".join(self._buffer).encode("utf-8")
        self._buffer = []
        for start in range(0, len(data), self._block_size):
            self._blob.append_block(data[start : start + self._block_size])

    def close(self) -> None:
        self.flush()


class AzureArtifacts:
    """Artifacts over a blob container client; `service` is the account's blob service client,
    which issues the user-delegation key a read link is signed with."""

    def __init__(
        self,
        container: Any,
        *,
        service: Any,
        block_size: int = DEFAULT_BLOCK_SIZE,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._container = container
        self._service = service
        self._block_size = block_size
        self._clock = clock

    def put(self, key: str, value: str | bytes) -> None:
        data = redact_text(value, where=key).encode("utf-8") if isinstance(value, str) else value
        self._container.upload_blob(key, data, overwrite=True)

    def get(self, key: str) -> bytes:
        try:
            return self._container.download_blob(key).readall()
        except Exception as error:
            if _is_missing(error):
                raise MissingArtifact(key) from error
            raise

    def list(self, prefix: str) -> list[str]:
        return sorted(blob.name for blob in self._container.list_blobs(name_starts_with=prefix))

    def delete(self, prefix: str) -> None:
        for key in self.list(prefix):
            try:
                self._container.delete_blob(key)
            except Exception as error:
                if not _is_missing(error):
                    raise

    def writer(self, key: str) -> ArtifactWriter:
        return _BlockWriter(self._container, key, self._block_size)

    def read_link(self, key: str, *, expires_in: timedelta) -> str:
        """A URL that reads the blob under `key` and stops working after `expires_in`."""
        blob = orchestration.import_sdk("azure", "azure.storage.blob")
        now = self._clock()
        expiry = now + expires_in
        delegation_key = self._service.get_user_delegation_key(now, expiry)
        token = blob.generate_blob_sas(
            account_name=self._container.account_name,
            container_name=self._container.container_name,
            blob_name=key,
            user_delegation_key=delegation_key,
            permission=blob.BlobSasPermissions(read=True),
            expiry=expiry,
        )
        return f"{self._container.url}/{key}?{token}"


def _default_credential(client_id: str | None) -> Any:
    identity = orchestration.import_sdk("azure", "azure.identity")
    return identity.ManagedIdentityCredential(client_id=client_id)


def _default_clients(account_url: str, credential: Any) -> tuple[Any, Any]:
    blob = orchestration.import_sdk("azure", "azure.storage.blob")
    service = blob.BlobServiceClient(account_url, credential=credential)
    return service.get_container_client(CONTAINER_NAME), service


def build_artifacts(
    installation: Installation,
    *,
    make_credential: Callable[[str | None], Any] = _default_credential,
    make_clients: Callable[[str, Any], tuple[Any, Any]] = _default_clients,
) -> AzureArtifacts:
    """Artifacts for an `azure` installation.

    `make_credential(client_id)` builds the managed-identity credential from the deployment's
    `identity_client_id`; `make_clients(account_url, credential)` builds the container client
    and the blob service client. Both default, where the SDK is imported, to the real ones.
    """
    settings = installation.config.deployment.azure
    if not settings.storage_account:
        raise orchestration.Refused(
            "deployment.azure.storage_account is not set: Azure artifacts need a storage account"
        )
    credential = make_credential(settings.identity_client_id)
    container, service = make_clients(
        f"https://{settings.storage_account}.blob.core.windows.net", credential
    )
    return AzureArtifacts(container, service=service)
