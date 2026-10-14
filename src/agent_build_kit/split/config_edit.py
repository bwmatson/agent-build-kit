"""Adding a repo's entry to the destination's abk.yaml by a checked text splice."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.model import Frozen

__all__ = ["ConfigEditError", "RepoEntry", "add_repo_entry"]


class ConfigEditError(ValueError):
    """The file's layout cannot be followed, or the result is not the old document plus the
    entry; nothing was written."""


class RepoEntry(Frozen):
    """What adding the entry did (or, with `write=False`, would do)."""

    already_declared: bool = False
    written: bool = False
    # `consumes:` entries of the block that name a repo the destination does not declare.
    missing_consumes: tuple[str, ...] = ()


def add_repo_entry(source: Path, destination: Path, repo: str, *, write: bool = True) -> RepoEntry:
    """Splice `repos.<repo>` of the `source` abk.yaml into the `destination` one."""
    raise NotImplementedError
