"""Which tests a unit's own commits define, and which a tree holds.

Read by the restack, to check that resolving a conflict did not drop one of the unit's own
tests, and by the adapt step's accounting.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from agent_build_kit.pipeline.shell import git

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)


def _test_spans(source: str) -> list[tuple[str, int, int]]:
    """Each `test_*` function's name and first and last line, decorators included."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    return [
        (
            node.name,
            min([d.lineno for d in node.decorator_list] + [node.lineno]),
            node.end_lineno or node.lineno,
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    ]


def _lines_in(spans: list[tuple[str, int, int]], first: int, count: int) -> set[str]:
    """Tests whose span holds any of `count` lines starting at `first`."""
    return {name for name, lo, hi in spans if count and first <= hi and first + count - 1 >= lo}


def defined_tests_in_range(tree: Path, old_base: str, old_head: str) -> list[str]:
    """Which tests the commit range `old_base..old_head` defined, deleted or edited inside.

    From which lines the range added or removed and which test each falls
    within, not from the diff's text: a test that only sits in the diff's
    context, beside an edit, is not the unit's.
    """
    names = git(
        tree, "diff", "-z", "--name-only", "--no-renames", old_base, old_head, "--", "*.py",
        check=False, errors="surrogateescape",
    ).stdout  # fmt: skip
    found: set[str] = set()
    for path in (p for p in names.split("\0") if p):
        diff = git(
            tree, "diff", "-U0", "--no-renames", old_base, old_head, "--", path,
            check=False, errors="replace",
        ).stdout  # fmt: skip
        old = git(tree, "show", f"{old_base}:{path}", check=False, errors="replace")
        new = git(tree, "show", f"{old_head}:{path}", check=False, errors="replace")
        old_spans = _test_spans(old.stdout) if old.returncode == 0 else []
        new_spans = _test_spans(new.stdout) if new.returncode == 0 else []
        for hunk in HUNK.finditer(diff):
            old_at, old_n, new_at, new_n = hunk.groups()
            found |= _lines_in(old_spans, int(old_at), int(old_n or 1))
            found |= _lines_in(new_spans, int(new_at), int(new_n or 1))
    return sorted(found)


def tests_in(tree: Path, ref: str = "") -> set[str]:
    """Every test function in the worktree as it stands, or in `ref` when one is given."""
    out = git(
        tree, "grep", "-hoE", "def test_[A-Za-z0-9_]+", *([ref] if ref else []), "--", "*.py",
        check=False,
    ).stdout  # fmt: skip
    return {line.removeprefix("def ").strip() for line in out.splitlines() if line.strip()}
