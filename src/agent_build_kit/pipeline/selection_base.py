"""The affected-selection data recorded on the base (spec: selection-data-comes-from-the-base):
a recording of the base's tip, kept with the commit it was made at under the pipeline's state, at
most a set number of them, refreshed when the base has moved and the last is older than a limit.
A recording is a full unit-test run of the base's tip, made by the toolchain profile's recording
command, that holds a unit-test slot at the rank behind every unit's check."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.check_runner import worktree_at
from agent_build_kit.pipeline.file_lock import Clock, atomic_move, atomic_write_text, try_file_lock
from agent_build_kit.pipeline.shell import Run, git_out
from agent_build_kit.pipeline.unit_test_slots import RECORDING_RANK, unit_test_slot
from agent_build_kit.profiles.base import RecordsSelectionData, ToolchainProfile

# Who the base recording's slot names as its holder.
RECORDING_HOLDER = "base-recording"


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


def _due(store: Path, tip: str, max_age_hours: float, now: datetime) -> bool:
    """Whether the base's tip is to be recorded: no recording yet, or the tip is not the last
    one recorded and that recording is older than the limit."""
    last = kept_recordings(store)
    if not last:
        return True
    return last[-1].commit != tip and now - last[-1].recorded_at > timedelta(hours=max_age_hours)


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
    if kept < 1:
        raise ValueError(f"kept must be above zero, not {kept}")
    tip = git_out(repo, "rev-parse", base)
    if not _due(store, tip, max_age_hours, now()):
        return None
    store.mkdir(parents=True, exist_ok=True)
    data = store / f"{tip}.data"
    # Recorded aside, then moved into place, so a failed run never touches a recording already
    # kept.
    aside = store / f"{tip}.data.tmp"
    try:
        record(tip, aside)
        atomic_move(aside, data)
    finally:
        aside.unlink(missing_ok=True)
    when = now()
    atomic_write_text(store / f"{tip}.json", json.dumps({"recorded_at": when.isoformat()}))
    for old in kept_recordings(store)[:-kept]:
        old.path.unlink(missing_ok=True)
        old.path.with_suffix(".json").unlink(missing_ok=True)
    _sweep_strays(store)
    return BaseRecording(commit=tip, recorded_at=when, path=data)


def _sweep_strays(store: Path) -> None:
    """Remove what a refresh that was cut short left: a data file with no metadata beside it
    (never listed, so never pruned), metadata with no data file, and an aside file."""
    for data in store.glob("*.data"):
        if not data.with_suffix(".json").exists():
            data.unlink(missing_ok=True)
    for meta in store.glob("*.json"):
        if not meta.with_suffix(".data").exists():
            meta.unlink(missing_ok=True)
    for aside in store.glob("*.data.tmp"):
        aside.unlink(missing_ok=True)


@runtime_checkable
class RecordingProfile(ToolchainProfile, RecordsSelectionData, Protocol):
    """A toolchain profile that also records selection data."""


def _recording_run(
    profile: RecordingProfile,
    *,
    repo: Path,
    run: Run,
    root_extras: list[str],
    workers: str | int,
    max_workers: int,
) -> Callable[[str, Path], None]:
    """The recording run: the profile's full test commands as recording commands, run in a
    checkout of the commit that is removed afterwards."""

    def record(commit: str, seed: Path) -> None:
        with worktree_at(repo, commit) as checkout:
            for command in profile.test_commands_all(
                checkout, root_extras=root_extras, workers=workers, max_workers=max_workers
            ):
                result = run(profile.seeding_command(command, seed), cwd=checkout)
                if result.returncode and not profile.tolerates_exit(command, result.returncode):
                    raise RuntimeError(
                        f"the recording run of {commit} failed (exit {result.returncode})"
                    )

    return record


def record_base_data(
    *,
    store: Path,
    repo: Path,
    base: str,
    profile: ToolchainProfile,
    run: Run,
    locks_dir: Path,
    limit: int | None,
    kept: int,
    max_age_hours: float,
    now: Callable[[], datetime],
    root_extras: list[str] | None = None,
    workers: str | int = "auto",
    max_workers: int = 8,
    clock: Clock | None = None,
) -> BaseRecording | None:
    """Refresh the base's recording with a full unit-test run that holds one of the `limit`
    unit-test slots at `RECORDING_RANK`, so a unit's check is served before it. One refresh runs
    at a time, whatever the limit: it holds a lock file beside the store, and a call that finds
    it held returns None because another refresh is already recording. None too when the profile
    records no selection data or nothing is due."""
    if not isinstance(profile, RecordingProfile):
        return None
    with try_file_lock(store.with_name(store.name + ".lock")) as taken:
        if not taken:
            return None
        if not _due(store, git_out(repo, "rev-parse", base), max_age_hours, now()):
            return None
        with unit_test_slot(
            locks_dir, limit, holder=RECORDING_HOLDER, rank=RECORDING_RANK, clock=clock
        ):
            return refresh_base_data(
                store=store,
                repo=repo,
                base=base,
                record=_recording_run(
                    profile,
                    repo=repo,
                    run=run,
                    root_extras=root_extras or [],
                    workers=workers,
                    max_workers=max_workers,
                ),
                kept=kept,
                max_age_hours=max_age_hours,
                now=now,
            )
