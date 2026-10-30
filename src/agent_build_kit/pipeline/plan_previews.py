"""The plan previews a dry-run tick saves: what the planner answered for a change, and the
digests of what it was asked under, kept in the state folder for a later tick to use."""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.pipeline.file_lock import atomic_write_text

FOLDER = "plan-previews"


def preview_path(state_dir: Path, change: str) -> Path:
    return state_dir / FOLDER / f"{change}.json"


def save_preview(state_dir: Path, change: str, *, answer: str, tasks: str, sizing: str) -> None:
    """Keep the planner's raw `answer` for `change`, with the `tasks.md` and sizing digests it
    was made under."""
    path = preview_path(state_dir, change)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"answer": answer, "tasks": tasks, "sizing": sizing}
    atomic_write_text(path, json.dumps(body, indent=2) + "\n")
