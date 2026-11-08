"""The affected-selection data recorded on the base (spec: selection-data-comes-from-the-base):
a recording of the base's tip, kept with the commit it was made at under the pipeline's state, at
most a set number of them, refreshed when the base has moved and the last is older than a limit."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from agent_build_kit.model import Frozen


class BaseRecording(Frozen):
    """One kept recording: the commit it was made at, when, and the data file."""

    commit: str
    recorded_at: datetime
    path: Path


def kept_recordings(store: Path) -> list[BaseRecording]:
    """The recordings in `store`, oldest first."""
    raise NotImplementedError


def refresh_base_data(
    *,
    store: Path,
    repo: Path,
    base: str,
    record: Callable[[str, Path], None],
    kept: int,
    max_age_hours: float,
    now: Callable[[], datetime],
) -> BaseRecording | None:
    """Record the base's tip when it has moved and the last recording is older than
    `max_age_hours`, by calling `record(commit, data_file)`; keep `kept` recordings. The new
    recording, or None when none was made."""
    raise NotImplementedError
