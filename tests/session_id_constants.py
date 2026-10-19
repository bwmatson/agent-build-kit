"""Constant session ids in test code: what the guard `test_no_shared_session_ids` reads."""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def duplicated_session_ids(root: Path) -> dict[str, list[Path]]:
    """Each string constant shaped like a session id (a UUID) that is defined in two or more
    `.py` files under `root`, with the files; a constant repeated inside one file is one."""
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
