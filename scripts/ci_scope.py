"""Say whether a CI run's changed paths include anything outside the planning paths.

Usage: ci_scope.py BASE HEAD, run in the repository. Prints `code=true` or
`code=false`, the line the workflow appends to its step output.

The planning paths are the specs, the pipeline's state, the two generated
documents and `abk.yaml` (the hook job lints that on its own).

This is a second copy of the planning paths the pipeline itself keeps (the specs
directory, the state directory and the two generated pages); it stays standalone
because the scope job runs before the environment is synced. Change the two together.
"""

from __future__ import annotations

import subprocess
import sys

PLANNING_PREFIXES = ("openspec/", "runs/")
PLANNING_FILES = ("docs/unit_graph.md", "docs/unit_cost.md", "abk.yaml")


def is_planning_path(path: str) -> bool:
    return path.startswith(PLANNING_PREFIXES) or path in PLANNING_FILES


def changed_paths(base: str, head: str) -> list[str]:
    done = subprocess.run(
        # No rename detection: a file moved into a planning path must list its old path too.
        ["git", "diff", "--name-only", "--no-renames", base, head],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.splitlines()


def main(argv: list[str]) -> int:
    base, head = argv
    code = not all(is_planning_path(path) for path in changed_paths(base, head))
    print(f"code={str(code).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
