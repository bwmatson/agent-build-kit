"""Constant session ids in test code: what the guard `test_no_shared_session_ids` reads."""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

# Claude's shape (a UUID) and the ACP fake's (`sess_` and a token).
SESSION_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|sess_[0-9A-Za-z_]+"
)


def duplicated_session_ids(root: Path) -> dict[str, list[Path]]:
    """Each string constant shaped like a session id (a UUID or `sess_` and a token) that is
    defined in two or more `.py` files under `root`, with the files; a constant repeated inside
    one file is one.
    Any UUID counts, whatever it names, so a fixture's message or object id must differ per file."""
    files: dict[str, set[Path]] = defaultdict(set)
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and SESSION_ID.fullmatch(node.value)
            ):
                files[node.value].add(path)
    return {sid: sorted(paths) for sid, paths in files.items() if len(paths) > 1}
