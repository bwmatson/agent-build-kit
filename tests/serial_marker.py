"""Test support: the guard that keeps a `serial` marker out of the tests and configuration.

A test that cannot run beside others is isolated, not marked. The guard reads the tracked test
and configuration files and names each one that holds the word, except the guard's own files and
the changelog.
"""

import re
from pathlib import Path

from tests.tracked_files import guarded_files, lines_of, test_tree_folders, tracked

# The word the guard keeps out. A test that needs it as data (a command still carrying the old
# selection) takes it from here, so the word stays in this file.
MARKER = "serial"

# The word on its own; "serial rerun(s)" is the pipeline's wording for a rerun alone, not a marker.
_WORD = re.compile(rf"\b{MARKER}\b(?! reruns?\b)")
# The guard's own files; the changelog is not read, as it is not a test or configuration file.
_OWN = frozenset({"tests/serial_marker.py", "tests/test_no_serial_marker_guard.py"})
# The suffixes of a configuration file at the root of a repository (a runner's or a package's).
_CONFIG_SUFFIXES = frozenset(
    {".toml", ".ini", ".cfg", ".json", ".yaml", ".yml", ".js", ".mjs", ".cjs", ".ts", ".mts"}
)


def serial_marker_problems(root: Path) -> list[str]:
    """One line per tracked test or configuration file below `root` that names `serial`."""
    # A root file is tracked when it is among the tracked paths of the repository.
    tracked_root = {path for path in tracked(root) if len(path.parts) == 1}
    configuration = [root / path for path in tracked_root if path.suffix in _CONFIG_SUFFIXES]
    files = {*guarded_files(root, under=test_tree_folders(root)), *configuration}
    problems: list[str] = []
    for path in sorted(files):
        relative = path.relative_to(root).as_posix()
        if relative in _OWN:
            continue
        for number, line in enumerate(lines_of(path), start=1):
            if _WORD.search(line):
                problems.append(f"{relative}:{number}: names the `{MARKER}` marker")
                break
    return problems
