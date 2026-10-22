"""The strict guard against an old test-kind spelling.

`old_spelling_problems` returns one `path:line` message per line of a source, test, web or
document file under `root` that carries an old spelling, and one message per file named for one.
The compatibility module, the rename tool and the tests of both, the two documents that explain
the rename and the changelog are exempt.
"""

from __future__ import annotations

import re
from pathlib import Path

# Built in parts so this file carries no old spelling for the guard to find.
OLD_SPELLING = re.compile("ti" + "er[-_ ]?([12]|one|two)", re.IGNORECASE)

SCANNED = ("src", "tests", "web/src", "docs", "scripts", ".github")
SKIPPED_PARTS = frozenset({"__pycache__", "node_modules"})
BUILT_WEB = Path("src/agent_build_kit/serve/static")

# The files that write an old spelling on purpose: the table of them, the tool that rewrites
# them, the tests of both and of the settings migration, and the documents that explain the
# rename and the runbooks that cite the old names and earlier changes by their fixed names.
EXEMPT_NAMES = frozenset(
    {
        "compat_names.py",
        "rename_test_kinds.py",
        "test_compat_names.py",
        "test_test_kind_settings_aliases.py",
        "CHANGELOG.md",
        "agent-efficient-coding-philosophy.md",
        "risk-tiered-review-design.md",
        "migrate-to-risk-tiered-review.md",
        "hold-a-e2e-split.md",
    }
)
EXEMPT_PREFIXES = ("test_rename_test_kinds", "test_config_migrate_test_kind_keys")


def exempt(path: Path) -> bool:
    return path.name in EXEMPT_NAMES or path.name.startswith(EXEMPT_PREFIXES)


def candidates(root: Path) -> list[Path]:
    found = [p for name in SCANNED for p in sorted((root / name).rglob("*"))]
    found += sorted(root.glob("*.md")) + [root / "pyproject.toml"]
    return [
        p
        for p in found
        if p.is_file()
        and not SKIPPED_PARTS & set(p.parts)
        and not p.is_relative_to(root / BUILT_WEB)
        and not exempt(p)
    ]


def old_spelling_problems(root: Path) -> list[str]:
    problems = []
    for path in candidates(root):
        name = path.relative_to(root).as_posix()
        if OLD_SPELLING.search(path.name):
            problems.append(f"{name}: the file name carries an old spelling")
        try:
            lines = path.read_text().splitlines()
        except UnicodeDecodeError:
            continue
        problems += [
            f"{name}:{number}: {line.strip()}"
            for number, line in enumerate(lines, start=1)
            if OLD_SPELLING.search(line)
        ]
    return problems
