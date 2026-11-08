"""The guard that keeps the old e2e marker name out of the tracked files.

`old_marker_problems` returns one `path:line` message per line of a tracked file under `root`
that holds the old name, the changelog excepted.
"""

from __future__ import annotations

from pathlib import Path


def old_marker_problems(root: Path) -> list[str]:
    raise NotImplementedError
