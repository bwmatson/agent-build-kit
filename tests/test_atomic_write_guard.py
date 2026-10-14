"""The guard against a state file being replaced without the shared write (spec: dry-cleanup).

A file is written through `atomic_write_text`; no source module outside the one that defines it
calls `os.replace` or replaces over a path from a temporary, scratch or partial name.
"""

from __future__ import annotations

import ast
import re

from tests.ecosystem_names import SOURCE_ROOT

SHARED = "pipeline/file_lock.py"
# Edits a user's own config file and must keep its mode, which a state-file write has no need to;
# it is not a state file.
KEEPS_MODE = frozenset({"runtimes/policy_apply.py"})
SIDE_NAME = re.compile(r"(tmp|temp|temporary|scratch|partial|aside)", re.IGNORECASE)


def receiver(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else ""


def replacements(tree: ast.AST) -> list[int]:
    """Lines that call `os.replace`, or `.replace(target)` on a temporary-named path."""
    lines = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "replace":
            continue
        owner = receiver(node.func.value)
        # `str.replace` takes two arguments; `Path.replace` takes the one target.
        if owner == "os" or (len(node.args) == 1 and SIDE_NAME.search(owner)):
            lines.append(node.lineno)
    return lines


def test_no_module_but_the_shared_one_replaces_a_file_from_a_temporary() -> None:
    problems = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        name = path.relative_to(SOURCE_ROOT).as_posix()
        if name == SHARED or name in KEEPS_MODE:
            continue
        problems += [f"{name}:{line}" for line in replacements(ast.parse(path.read_text()))]

    assert not problems, "write through atomic_write_text instead:\n" + "\n".join(problems)
