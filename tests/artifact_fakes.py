"""A stand-in Artifacts implementation: keys held in a dict, no file under any state directory.

A caller that still opens a path writes nothing the stand-in sees, so a test reading its keys
fails for it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from agent_build_kit.orchestration.artifacts import ArtifactWriter, MissingArtifact
from agent_build_kit.redaction import redact_text


class _MemoryWriter:
    def __init__(self, store: MemoryArtifacts, key: str) -> None:
        self._store = store
        self._key = key

    def write(self, text: str) -> None:
        held = self._store.blobs.get(self._key, b"")
        self._store.blobs[self._key] = held + redact_text(text, where=self._key).encode()

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class MemoryArtifacts:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def put(self, key: str, value: str | bytes) -> None:
        if isinstance(value, str):
            value = redact_text(value, where=key).encode()
        self.blobs[key] = value

    def get(self, key: str) -> bytes:
        try:
            return self.blobs[key]
        except KeyError as error:
            raise MissingArtifact(key) from error

    def list(self, prefix: str) -> list[str]:
        return sorted(key for key in self.blobs if key.startswith(prefix))

    def delete(self, prefix: str) -> None:
        for key in self.list(prefix):
            del self.blobs[key]

    def writer(self, key: str) -> ArtifactWriter:
        self.blobs.setdefault(key, b"")
        return _MemoryWriter(self, key)


@contextmanager
def given_the_artifacts() -> Iterator[None]:
    """Wrap the code under test that is handed a `MemoryArtifacts`. A module that still takes a
    directory fails the test with an assertion saying so, not with a bare `TypeError`."""
    try:
        yield
    except TypeError as error:
        raise AssertionError(
            f"the module still takes a directory, not the Artifacts: {error}"
        ) from error
