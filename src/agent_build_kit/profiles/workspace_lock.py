"""Finding the lock file a project uses: its own, or its workspace root's when an ancestor
manifest names the project as a member. Never looks above the checkout."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from agent_build_kit import path_patterns
from agent_build_kit.path_discovery import checkout_root, find_up


def workspace_lock(
    project: Path, names: Sequence[str], members_of: Callable[[Path], list[str]]
) -> Path | None:
    """The nearest entry of `names` in the project's folder, or in a folder above it (up to the
    checkout) whose manifest, read by `members_of`, lists the project as a workspace member."""
    project = project.resolve()
    stop = checkout_root(project)
    if stop is None:
        return None

    def is_ours(candidate: Path) -> bool:
        folder = candidate.parent
        return folder == project or path_patterns.matches_any(
            members_of(folder), project.relative_to(folder).as_posix()
        )

    return find_up(names, project, stop=stop, accept=is_ours)
