"""Local state about cassettes that must not churn git: when each was last used and for
how many runs it has waited for review. It sits in the cassette directory and is ignored."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent_build_kit.model import Frozen

STATE_FILE = "state.json"


class ReplayState(Frozen):
    # Both keyed by the cassette's path under the cassette directory, with `/` separators.
    last_hit_at: dict[str, datetime] = {}
    unreviewed_runs: dict[str, int] = {}


def read_state(directory: Path) -> ReplayState:
    """The state kept in `directory`; none yet is an empty one."""
    path = directory / STATE_FILE
    if not path.is_file():
        return ReplayState()
    return ReplayState.model_validate_json(path.read_text())


def write_state(directory: Path, state: ReplayState) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    # The directory ignores its own state file, so a repository needs no rule for it.
    (directory / ".gitignore").write_text(f"{STATE_FILE}\n")
    (directory / STATE_FILE).write_text(state.model_dump_json())
