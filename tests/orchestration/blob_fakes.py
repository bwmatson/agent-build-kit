"""An in-memory stand-in for the Azure blob container and service clients.

It follows the shape of the SDK's `ContainerClient`, `BlobClient` and `BlobServiceClient` for
the calls the Azure Artifacts implementation makes: the same method names, the same overwrite
rules (`create_append_blob` replaces what is there, `upload_blob` refuses an existing blob
unless told to overwrite) and a missing blob raised as `ResourceNotFoundError`.
"""

from __future__ import annotations

import base64
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from azure.core import MatchConditions

ACCOUNT = "fakeaccount"
CONTAINER = "fakecontainer"


class ResourceNotFoundError(Exception):
    """The name the SDK gives the error for a blob that does not exist."""


class ResourceExistsError(Exception):
    """The name the SDK gives the error for an upload over a blob without `overwrite`."""


class HttpResponseError(Exception):
    """The SDK's error for a refused request, with the service's error code."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class FakeDownload:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def readall(self) -> bytes:
        return self._data


class FakeBlobClient:
    def __init__(self, container: FakeContainer, name: str) -> None:
        self._container = container
        self._name = name

    def exists(self) -> bool:
        return self._name in self._container.blobs

    def create_append_blob(self, match_condition: MatchConditions | None = None) -> None:
        if match_condition == MatchConditions.IfMissing and self._name in self._container.blobs:
            raise ResourceExistsError(self._name)
        self._container.blobs[self._name] = b""
        self._container.append_blobs.add(self._name)

    def append_block(self, data: str | bytes) -> None:
        if self._name not in self._container.blobs:
            raise ResourceNotFoundError(self._name)
        if self._name not in self._container.append_blobs:
            # What the service answers when a block blob is appended to.
            raise HttpResponseError("InvalidBlobType")
        body = data.encode() if isinstance(data, str) else data
        self._container.blobs[self._name] += body
        self._container.append_calls.append((self._name, body))


class FakeContainer:
    """Blobs by name, with a record of the append calls and of what was uploaded."""

    container_name = CONTAINER
    account_name = ACCOUNT
    url = f"https://{ACCOUNT}.blob.core.windows.net/{CONTAINER}"

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.append_blobs: set[str] = set()
        self.append_calls: list[tuple[str, bytes]] = []

    def upload_blob(self, name: str, data: str | bytes, overwrite: bool = False) -> None:
        if name in self.blobs and not overwrite:
            raise ResourceExistsError(name)
        self.blobs[name] = data.encode() if isinstance(data, str) else bytes(data)
        self.append_blobs.discard(name)

    def download_blob(self, blob: str) -> FakeDownload:
        if blob not in self.blobs:
            raise ResourceNotFoundError(blob)
        return FakeDownload(self.blobs[blob])

    def list_blobs(self, name_starts_with: str | None = None) -> list[Any]:
        prefix = name_starts_with or ""
        return [
            SimpleNamespace(name=name) for name in sorted(self.blobs) if name.startswith(prefix)
        ]

    def delete_blob(self, blob: str) -> None:
        if blob not in self.blobs:
            raise ResourceNotFoundError(blob)
        del self.blobs[blob]
        self.append_blobs.discard(blob)

    def get_blob_client(self, blob: str) -> FakeBlobClient:
        return FakeBlobClient(self, blob)


class FakeService:
    """The blob service client: it issues user-delegation keys and records the requests."""

    account_name = ACCOUNT

    def __init__(self) -> None:
        self.key_requests: list[tuple[datetime, datetime]] = []

    def get_user_delegation_key(
        self, key_start_time: datetime, key_expiry_time: datetime
    ) -> SimpleNamespace:
        self.key_requests.append((key_start_time, key_expiry_time))
        return SimpleNamespace(
            signed_oid="00000000-0000-0000-0000-000000000001",
            signed_tid="00000000-0000-0000-0000-000000000002",
            signed_start=key_start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            signed_expiry=key_expiry_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            signed_service="b",
            signed_version="2023-11-03",
            signed_delegated_user_tid=None,
            value=base64.b64encode(b"fake-delegation-key").decode(),
        )
