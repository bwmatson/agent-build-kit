"""Rewrites the old spellings of the test kinds to the new ones over the paths it is given.

Run as `python -m agent_build_kit.rename_test_kinds --paths <path>...`.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


class PathOutsideRoot(ValueError):
    """A path given to the tool lies outside the root it works under."""


def rename_paths(root: Path, paths: Sequence[Path]) -> list[Path]:
    """Rewrite the old spellings in `paths` (files or folders under `root`) and rename the
    files that carry one; returns the files changed, relative to `root`. Raises
    `PathOutsideRoot`, changing nothing, when a path is outside `root`."""
    raise NotImplementedError


def main(argv: Sequence[str] | None = None, *, root: Path | None = None) -> int:
    """The command line: `--paths` names what to rewrite; each changed file is printed, one per
    line. `root` is the framework repository unless given. Returns 2 for a refused path."""
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
