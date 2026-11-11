"""Where a module's artifacts live, given what it was handed.

A module is handed the installation's `Artifacts`. A directory is still accepted, as the
artifacts of one folder: its name is the key prefix and its parent the root.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.orchestration.artifacts import Artifacts, MissingArtifact
from agent_build_kit.orchestration.local.artifacts import DirectoryArtifacts


def scoped(target: Artifacts | Path, folder: str) -> tuple[Artifacts, str]:
    """The Artifacts to use and the key prefix (ending in `/`) of the module's folder in it."""
    if isinstance(target, Path):
        return DirectoryArtifacts(target.parent), f"{target.name}/"
    return target, f"{folder}/"


def append_redacted(store: Artifacts, key: str, text: str) -> None:
    """Append text the caller has already redacted, as bytes, which a store keeps unchanged.
    The caller redacts first when it must keep the shape of what it writes (a JSON line, a
    notice on a line of its own), which redacting a second time would break. A store that can
    append bytes does; any other has the key read and put back."""
    data = text.encode()
    append = getattr(store, "append", None)
    if append is not None:
        append(key, data)
        return
    try:
        held = store.get(key)
    except MissingArtifact:
        held = b""
    store.put(key, held + data)


def rooted(target: Artifacts | Path) -> Artifacts:
    """The Artifacts for a module whose keys start at the root; a directory is the root."""
    return DirectoryArtifacts(target) if isinstance(target, Path) else target
