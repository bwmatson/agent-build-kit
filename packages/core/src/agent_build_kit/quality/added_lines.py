"""A unit's added lines, read from git against the merge-base and closed to tampering."""

from pathlib import Path

from agent_build_kit.model import Frozen


class AddedLinesError(Exception):
    """The reading failed; it names the step and git's message and is never a pass."""


class AddedFile(Frozen):
    """One file's part of a unit's diff."""

    path: str
    added: frozenset[int]
    is_new: bool
    renamed_from: str | None = None
    removed: tuple[str, ...] = ()


def read_added_lines(root: Path, base: str) -> dict[str, AddedFile]:
    """Each changed file's added line numbers against the merge-base of `base` and HEAD, by path."""
    raise NotImplementedError
