"""The Artifacts interface: the files a unit leaves behind, written and read by key.

A key is the artifact's path relative to the state directory, with `/` separators
(`unit-logs/<name>.log`, `transcripts/<file>.jsonl`). Implementations redact text with the
active redactor before storing it; bytes are stored unchanged.
"""

from __future__ import annotations

from typing import Protocol

# The name the implementations register under in the deployment registry.
INTERFACE = "artifacts"


class MissingArtifact(KeyError):
    """The key names nothing stored."""


class ArtifactWriter(Protocol):
    """An append handle for a log that grows."""

    def write(self, text: str) -> None:
        """Append `text`, redacted."""
        raise NotImplementedError

    def flush(self) -> None:
        """Make what was written readable by `Artifacts.get`."""
        raise NotImplementedError

    def close(self) -> None:
        """Flush and release the handle."""
        raise NotImplementedError


class Artifacts(Protocol):
    def put(self, key: str, value: str | bytes) -> None:
        """Store `value` under `key`; text is redacted first, bytes are stored unchanged."""
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        """The bytes stored under `key`; raises `MissingArtifact` when there are none."""
        raise NotImplementedError

    def list(self, prefix: str) -> list[str]:
        """The sorted keys that start with `prefix`, and no others."""
        raise NotImplementedError

    def delete(self, prefix: str) -> None:
        """Remove every key that starts with `prefix`."""
        raise NotImplementedError

    def writer(self, key: str) -> ArtifactWriter:
        """An append handle on `key`."""
        raise NotImplementedError
