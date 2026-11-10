"""The local Artifacts implementation: keys are files under the installation's state directory."""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

from agent_build_kit.installation import Installation
from agent_build_kit.orchestration.artifacts import ArtifactWriter, MissingArtifact
from agent_build_kit.redaction import redact_text


class _FileWriter:
    def __init__(self, path: Path, key: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._key = key
        self._handle: TextIO = path.open("a", encoding="utf-8")

    def write(self, text: str) -> None:
        self._handle.write(redact_text(text, where=self._key))

    def flush(self) -> None:
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


class LocalArtifacts:
    def __init__(self, installation: Installation) -> None:
        self.root = installation.state_dir

    def _path(self, key: str) -> Path:
        return self.root / key

    def put(self, key: str, value: str | bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, str):
            path.write_text(redact_text(value, where=key), encoding="utf-8")
        else:
            path.write_bytes(value)

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError) as error:
            raise MissingArtifact(key) from error

    def list(self, prefix: str) -> list[str]:
        if not self.root.is_dir():
            return []
        keys = (path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
        return sorted(key for key in keys if key.startswith(prefix) and self._path(key).is_file())

    def delete(self, prefix: str) -> None:
        for key in self.list(prefix):
            self._path(key).unlink()

    def writer(self, key: str) -> ArtifactWriter:
        return _FileWriter(self._path(key), key)
