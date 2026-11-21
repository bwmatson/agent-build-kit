"""The local Artifacts implementation: keys are files under the installation's state directory."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from agent_build_kit.orchestration.artifacts import ArtifactWriter, MissingArtifact
from agent_build_kit.redaction import redact_text

if TYPE_CHECKING:
    from agent_build_kit.installation import Installation


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


class DirectoryArtifacts:
    """Keys as files under a directory."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / key

    def put(self, key: str, value: str | bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, str):
            path.write_text(redact_text(value, where=key), encoding="utf-8")
        else:
            path.write_bytes(value)

    def append(self, key: str, data: bytes) -> None:
        """Add bytes to the end of `key`, unchanged: for text its writer already redacted."""
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as handle:
            handle.write(data)

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError) as error:
            raise MissingArtifact(key) from error

    def list(self, prefix: str) -> list[str]:
        # Only the directory the prefix names is walked, not every artifact beside it.
        folder = self.root / prefix.rpartition("/")[0]
        if not folder.is_dir():
            return []
        keys = (path.relative_to(self.root).as_posix() for path in folder.rglob("*"))
        return sorted(key for key in keys if key.startswith(prefix) and self._path(key).is_file())

    def delete(self, prefix: str) -> None:
        for key in self.list(prefix):
            path = self._path(key)
            path.unlink()
            # A folder left empty goes too, so a removed bundle leaves nothing behind; the
            # top folder of a kind of artifact stays.
            for folder in path.parents:
                if folder.parent == self.root:
                    break
                try:
                    folder.rmdir()
                except OSError:
                    break

    def writer(self, key: str) -> ArtifactWriter:
        return _FileWriter(self._path(key), key)


class LocalArtifacts(DirectoryArtifacts):
    """The installation's artifacts: files under its state directory."""

    def __init__(self, installation: Installation) -> None:
        super().__init__(installation.state_dir)
