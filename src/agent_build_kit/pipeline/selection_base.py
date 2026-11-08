"""The affected-selection data recorded on the base (spec: selection-data-comes-from-the-base):
a recording of the base's tip, kept with the commit it was made at under the pipeline's state, at
most a set number of them, refreshed when the base has moved and the last is older than a limit."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.shell import git_out


class BaseRecording(Frozen):
    """One kept recording: the commit it was made at, when, and the data file."""

    commit: str
    recorded_at: datetime
    path: Path


def kept_recordings(store: Path) -> list[BaseRecording]:
    """The recordings in `store`, oldest first."""
    found: list[BaseRecording] = []
    for meta in store.glob("*.json"):
        data = meta.with_suffix(".data")
        if not data.is_file():
            continue
        try:
            when = datetime.fromisoformat(json.loads(meta.read_text())["recorded_at"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        found.append(BaseRecording(commit=meta.stem, recorded_at=when, path=data))
    return sorted(found, key=lambda r: (r.recorded_at, r.commit))


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
    tip = git_out(repo, "rev-parse", base)
    last = kept_recordings(store)
    if last and (
        last[-1].commit == tip or now() - last[-1].recorded_at <= timedelta(hours=max_age_hours)
    ):
        return None
    store.mkdir(parents=True, exist_ok=True)
    data = store / f"{tip}.data"
    record(tip, data)
    when = now()
    (store / f"{tip}.json").write_text(json.dumps({"recorded_at": when.isoformat()}))
    for old in kept_recordings(store)[:-kept]:
        old.path.unlink(missing_ok=True)
        old.path.with_suffix(".json").unlink(missing_ok=True)
    return BaseRecording(commit=tip, recorded_at=when, path=data)
