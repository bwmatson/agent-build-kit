"""The plan previews a dry-run tick saves: what the planner answered for a change, and the
digests of what it was asked under, kept in the state folder for a later tick to use."""

from __future__ import annotations

import json
from collections.abc import Collection
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


def load_preview(state_dir: Path, change: str, *, tasks: str, sizing: str) -> str | None:
    """The saved planner answer for `change` when it was made under these two digests, else
    None. A preview made under others, or one that cannot be read, is of no use."""
    try:
        body = json.loads(preview_path(state_dir, change).read_text())
        answer = body["answer"]
        made_under = (body["tasks"], body["sizing"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if made_under != (tasks, sizing) or not isinstance(answer, str):
        return None
    return answer


def remove_preview(state_dir: Path, change: str) -> None:
    preview_path(state_dir, change).unlink(missing_ok=True)


def sweep_previews(state_dir: Path, existing: Collection[str]) -> None:
    """Remove the previews of changes that are not in `existing`."""
    for path in (state_dir / FOLDER).glob("*.json"):
        if path.stem not in existing:
            path.unlink(missing_ok=True)
