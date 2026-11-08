"""The guard that keeps the old e2e marker name out of the tracked files.

`old_marker_problems` returns one `path:line` message per line of a tracked file under `root`
that holds the old name, the changelog excepted.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.cli.doctor import OLD_E2E_MARKER
from tests.tracked_files import guarded_files, lines_of

CHANGELOG = "CHANGELOG.md"


def old_marker_problems(root: Path) -> list[str]:
    problems = []
    for path in guarded_files(root):
        name = path.relative_to(root).as_posix()
        if name == CHANGELOG:
            continue
        problems += [
            f"{name}:{number}: {line.strip()}"
            for number, line in enumerate(lines_of(path), start=1)
            if OLD_E2E_MARKER in line
        ]
    return problems
