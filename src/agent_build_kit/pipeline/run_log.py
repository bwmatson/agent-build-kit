"""A file per unit run, named for the unit (docs/architecture.md).

The tick prints everything to its own output; this keeps each unit's slice of
it where a person looking for that unit can find it.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable, Collection
from datetime import datetime, timedelta
from pathlib import Path

from agent_build_kit.compat_names import moved_to_current_name, old_spelling
from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.units import Unit, unit_file_prefix
from agent_build_kit.redaction import redact_text

# How many runs of one unit are kept; older ones go when a new one is written.
RUNS_KEPT = 3

# What each further line of a multi-line message starts with, so every line
# that begins at the margin is a new entry and the file stays parsable by line.
CONTINUATION = "    "


# What follows a unit's prefix in a log's name: the run's start stamp and its dash.
_STAMP = r"\d{8}-\d{6}-"
_UNIT_LOG = re.compile(rf"(?P<change>.+)-(?P<number>\d{{2,}})(?P<suffix>(?:-s\d+)*)-{_STAMP}")


_OUTPUT_DIR = "e2e-output"

# The name the directory had under the kind's old spelling.
_OLD_OUTPUT_DIR = f"{old_spelling(TestTier.E2E_TEST)}-output"


def run_log_dir(state_dir: Path) -> Path:
    """The directory of its own, under the state directory."""
    return state_dir / "unit-logs"


def e2e_output_dir(state_dir: Path) -> Path:
    """The directory of the full output of each e2e-test run, under the state directory. One
    left under the old name is moved to the current one first."""
    return moved_to_current_name(state_dir, _OUTPUT_DIR, _OLD_OUTPUT_DIR)


def append_e2e_output(directory: Path, unit: Unit, started: datetime, text: str) -> Path:
    """Append `text` to the unit's file for the e2e-test run begun at `started`, and
    return it. The files of the unit beyond `RUNS_KEPT` are removed first. The file
    is a diagnostic copy, so a write that fails is dropped."""
    path = directory / run_log_name(unit, started, "e2e-test")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        _prune(directory, unit, keep=RUNS_KEPT - (0 if path.exists() else 1))
        with path.open("a") as file:
            file.write(text)
    except (OSError, ValueError):
        pass
    return path


# The most of a failing run's output a bundle keeps, in bytes.
FAILURE_OUTPUT_CAP = 5_000_000


def failure_bundles_dir(state_dir: Path) -> Path:
    """The directory of the bundles of failing unit-test runs, under the state directory."""
    return state_dir / "test-failures"


def write_failure_bundle(
    directory: Path,
    unit_id: str,
    change: str,
    started: datetime,
    *,
    output: str,
    context: dict[str, object],
    machine: dict[str, object],
    worktree: dict[str, object],
    pointed: Collection[Path] = (),
    cap: int = FAILURE_OUTPUT_CAP,
) -> Path:
    """Save a failing unit-test run as `<directory>/<unit prefix><stamp>/` and return it:
    `output.txt` (redacted, cut at `cap` bytes with a note), `context.json`, `machine.json` and
    `worktree.json` (redacted). The unit's bundles beyond `RUNS_KEPT` go, except those in
    `pointed`. The bundle is a diagnostic copy, so a write that fails is dropped."""
    path = directory / f"{unit_file_prefix(unit_id, change)}{started:%Y%m%d-%H%M%S}"
    text = redact_text(output, where="failure bundle")
    encoded = text.encode()
    if len(encoded) > cap:
        text = (
            encoded[:cap].decode(errors="ignore")
            + f"\n[output cut at {cap} bytes; {len(encoded) - cap} more were dropped]\n"
        )
    try:
        path.mkdir(parents=True, exist_ok=True)
        (path / "output.txt").write_text(text)
        for name, facts in (("context", context), ("machine", machine), ("worktree", worktree)):
            body = redact_text(json.dumps(facts, indent=2, default=str), where="failure bundle")
            (path / f"{name}.json").write_text(body)
        _prune_bundles(directory, unit_file_prefix(unit_id, change), pointed)
    except (OSError, ValueError):
        pass
    return path


def _prune_bundles(directory: Path, prefix: str, pointed: Collection[Path]) -> None:
    """Remove the unit's bundles beyond the newest `RUNS_KEPT`, except those pointed at."""
    keep = {p.resolve() for p in pointed}
    named = re.compile(re.escape(prefix) + r"\d{8}-\d{6}$")
    bundles = sorted(path for path in directory.glob(f"{prefix}*") if named.match(path.name))
    for old in bundles[:-RUNS_KEPT]:
        if old.resolve() not in keep:
            shutil.rmtree(old, ignore_errors=True)


def _unit_prefix(unit: Unit) -> str:
    return unit_file_prefix(unit.id, unit.change)


def run_log_name(unit: Unit, started: datetime, step: str) -> str:
    """`<change>-<nn>-<YYYYMMDD-HHMMSS>-<step>.log`"""
    return f"{_unit_prefix(unit)}{started:%Y%m%d-%H%M%S}-{step}.log"


class RunLog:
    """One run's file: a header on open, the unit's lines, an outcome on close.

    A diagnostic copy, so it never affects the build: a write that fails
    (unwritable directory, full disk, an encoding the locale cannot write) is
    dropped, and reported once through `report`.
    """

    def __init__(
        self,
        directory: Path,
        unit: Unit,
        *,
        step: str,
        model: str,
        base: str,
        started: datetime,
        report: Callable[[str], None] = lambda message: None,
    ) -> None:
        self._name = run_log_name(unit, started, step)
        self._path = directory / self._name
        self._report = report
        self._working = True
        try:
            directory.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                f"unit: {unit.id}\nchange: {unit.change}\nstep: {step}\nmodel: {model}\n"
                f"base: {base}\nstarted: {started.isoformat()}\n\n"
            )
            _prune(directory, unit)
        except (OSError, ValueError) as error:
            self._failed(error)

    @property
    def name(self) -> str:
        return self._name

    @property
    def writing(self) -> bool:
        """False once the file could not be created or written to."""
        return self._working

    def _failed(self, error: Exception) -> None:
        if self._working:
            self._working = False
            self._report(f"run log {self._name} not written: {type(error).__name__}: {error}")

    def _append(self, text: str) -> None:
        if not self._working:
            return
        try:
            with self._path.open("a") as file:
                file.write(text)
        except (OSError, ValueError) as error:
            self._failed(error)

    def emit(self, message: str) -> None:
        message = redact_text(message, where="run log")
        first, *rest = message.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self._append("".join(f"{line}\n" for line in [first, *(CONTINUATION + r for r in rest)]))

    def close(self, outcome: str) -> None:
        self._append(f"\noutcome: {outcome}\n")


def _unit_logs(directory: Path, prefix: str) -> list[Path]:
    """The files of the unit whose prefix this is: a stamp follows it directly,
    so a change whose name merely begins with another's is not matched."""
    pattern = re.compile(re.escape(prefix) + _STAMP)
    return sorted(path for path in directory.glob(f"{prefix}*") if pattern.match(path.name))


def _prune(directory: Path, unit: Unit, *, keep: int = RUNS_KEPT) -> None:
    for path in _unit_logs(directory, _unit_prefix(unit))[: -keep or None]:
        path.unlink(missing_ok=True)


def remove_change_logs(directory: Path, change: str) -> None:
    """Drop every unit log of a change. The logs are a diagnostic copy: a
    directory that cannot be read leaves the archive it follows standing."""
    try:
        for path in directory.iterdir():
            if (match := _UNIT_LOG.match(path.name)) and match["change"] == change:
                path.unlink(missing_ok=True)
    except OSError:
        return


def _written_before(path: Path, cutoff: float) -> bool:
    try:
        return path.stat().st_mtime < cutoff
    except OSError:
        return False


def remove_old_logs(directory: Path, ledger: Path, *, days: int, now: datetime) -> None:
    """Remove each unit log last written more than `days` before `now` whose unit has a
    `summary` line in `ledger`; a log whose unit has none is kept."""
    cutoff = (now - timedelta(days=days)).timestamp()
    try:
        paths = list(directory.iterdir())
    except OSError:
        return
    candidates = [p for p in paths if _UNIT_LOG.match(p.name) and _written_before(p, cutoff)]
    if not candidates:
        return  # the ledger is read only when a log is old enough to go
    try:
        lines = ledger.read_text().splitlines()
    except OSError:
        return
    summarised: set[str] = set()
    for line in lines:
        try:
            raw = json.loads(line)
            if raw.get("kind") == "summary":
                summarised.add(str(raw["unit"]))
        except (ValueError, AttributeError, KeyError):
            continue
    for path in candidates:
        match = _UNIT_LOG.match(path.name)
        if match and f"{match['change']}/{int(match['number'])}{match['suffix']}" in summarised:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue
