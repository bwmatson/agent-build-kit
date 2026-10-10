"""A unit's actual size: the changed lines of its pull request as the host
counts them, less generated files. The planner only estimates; this is what
landed, and it is compared with the ceiling without ever blocking a unit."""

from __future__ import annotations

from collections.abc import Iterable
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from agent_build_kit.config import active
from agent_build_kit.forges import FileChange


def is_generated(path: str, patterns: Iterable[str]) -> bool:
    """Whether a pattern matches the whole path or just the file's name."""
    name = PurePosixPath(path).name
    return any(fnmatchcase(path, p) or fnmatchcase(name, p) for p in patterns)


def actual_lines(changes: Iterable[FileChange]) -> int:
    """Additions plus deletions over every file that is not generated."""
    patterns = active().generated_file_patterns()
    return sum(
        change.additions + change.deletions
        for change in changes
        if not is_generated(change.path, patterns)
    )


def over_ceiling(lines: int | None) -> bool:
    return lines is not None and lines > active().limits.max_unit_lines
