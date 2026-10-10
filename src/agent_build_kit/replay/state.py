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
    raise NotImplementedError


def write_state(directory: Path, state: ReplayState) -> None:
    raise NotImplementedError
