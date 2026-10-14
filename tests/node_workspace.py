"""An npm workspace built from manifests only, for the node profile's member, tier-1 and
tier-2 tests."""

from __future__ import annotations

import json
from pathlib import Path


def manifest(directory: Path, name: str | None = None, **fields: object) -> None:
    """Write `directory/package.json`, named `name` when given."""
    directory.mkdir(parents=True, exist_ok=True)
    body = {"name": name, **fields} if name else dict(fields)
    (directory / "package.json").write_text(json.dumps(body))


def workspace(root: Path, members: list[str]) -> None:
    """A root manifest listing `members` as its workspaces, and a manifest in each, named
    after its directory."""
    manifest(root, "root", private=True, workspaces=members)
    for member in members:
        manifest(root / member, member.rsplit("/", 1)[-1])


def touch(root: Path, *paths: str) -> None:
    """Empty files at `paths` under `root`, with their directories."""
    for path in paths:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text("")
