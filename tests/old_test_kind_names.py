"""The strict guard against an old test-kind spelling.

`old_spelling_problems` returns one `path:line` message per line of a source, test, web or
document file under `root` that carries an old spelling, and one message per file named for one.
The compatibility module, the tests of it and of the settings migration, the two documents
that explain the rename and the changelog are exempt.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.tracked_files import guarded_files, lines_of, planning_dirs

# Built in parts so this file carries no old spelling for the guard to find.
OLD_SPELLING = re.compile("ti" + "er[-_ ]?([12]|one|two)", re.IGNORECASE)

SCANNED = ("src", "tests", "web/src", "docs", "scripts", ".github")

# The files that write an old spelling on purpose: the table of them, the tests of it and of
# the settings migration, and the documents that explain the
# rename and the runbooks that cite the old names and earlier changes by their fixed names.
EXEMPT_NAMES = frozenset(
    {
        "compat_names.py",
        "test_compat_names.py",
        "test_test_kind_settings_aliases.py",
        "CHANGELOG.md",
        "agent-efficient-coding-philosophy.md",
        "risk-tiered-review-design.md",
        "migrate-to-risk-tiered-review.md",
        "hold-a-e2e-split.md",
    }
)
EXEMPT_PREFIXES = ("test_config_migrate_test_kind_keys",)


def exempt(path: Path, reports: Path) -> bool:
    """A named file, or a track report under the root-relative `reports` folder: those record
    what the tracks saw, unit ids included."""
    return (
        reports in path.parents
        or path.name in EXEMPT_NAMES
        or path.name.startswith(EXEMPT_PREFIXES)
    )


def candidates(root: Path) -> list[Path]:
    dirs = planning_dirs(root)
    reports = root / dirs.reports_dir
    found = guarded_files(root, under=SCANNED, names=["pyproject.toml"], dirs=dirs)
    found += [p for p in guarded_files(root, suffixes=[".md"], dirs=dirs) if p.parent == root]
    return [p for p in found if not exempt(p, reports)]


def old_spelling_problems(root: Path) -> list[str]:
    problems = []
    for path in candidates(root):
        name = path.relative_to(root).as_posix()
        if OLD_SPELLING.search(path.name):
            problems.append(f"{name}: the file name carries an old spelling")
        problems += [
            f"{name}:{number}: {line.strip()}"
            for number, line in enumerate(lines_of(path), start=1)
            if OLD_SPELLING.search(line)
        ]
    return problems
