"""Local state about cassettes that must not churn git: when each was last used and for
how many runs it has waited for review, and the last run's report. They sit in the cassette
directory and are ignored."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.replay.report import RunReport

STATE_FILE = "state.json"
REPORT_FILE = "report.json"


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


def _prepare(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    # The directory ignores its own local files, so a repository needs no rule for them.
    (directory / ".gitignore").write_text(f"{STATE_FILE}\n{REPORT_FILE}\n")


def write_state(directory: Path, state: ReplayState) -> None:
    _prepare(directory)
    (directory / STATE_FILE).write_text(state.model_dump_json())


def write_report(directory: Path, report: RunReport) -> None:
    """The run's report, for whatever reads it by machine."""
    _prepare(directory)
    (directory / REPORT_FILE).write_text(report.model_dump_json())
