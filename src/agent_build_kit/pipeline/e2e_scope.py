"""What an `[e2e-test]` group may name: tests, test support, docs, the changelog and declared
support. The reader of a task line's paths, the classifier shared by the `abk tags` warning and
the build's checks guard, and the warning itself."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.config import RepoConfig
from agent_build_kit.installation import Installation


def task_paths(line: str) -> list[str]:
    """The repo paths a task line names in backticks."""
    raise NotImplementedError


def is_product_path(path: str, repo: RepoConfig | None, support: Sequence[str] = ()) -> bool:
    """Whether `path` is none of: a test path of the repo's profile for the path's project, a
    doc path, the repo's changelog, or declared support (a trailing `/` covers a directory)."""
    raise NotImplementedError


def unscoped_task_paths(
    paths: Sequence[str], repo: RepoConfig | None, support: Sequence[str] = ()
) -> list[str]:
    """The paths of one task line that are product code: `is_product_path`, except that a
    `scripts/` path is allowed when the line also names a test path."""
    raise NotImplementedError


def product_path_warnings(inst: Installation, path: Path) -> list[str]:
    """One warning per path and `[e2e-test]` group of a tasks file that names product code,
    as `abk tags` and `abk check` print it."""
    raise NotImplementedError
