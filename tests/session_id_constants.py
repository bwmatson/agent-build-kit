"""Constant session ids in test code: what the guard `test_no_shared_session_ids` reads."""

from __future__ import annotations

from pathlib import Path


def duplicated_session_ids(root: Path) -> dict[str, list[Path]]:
    """Each string constant shaped like a session id (a UUID) that is defined in two or more
    `.py` files under `root`, with the files; a constant repeated inside one file is one."""
    raise NotImplementedError
