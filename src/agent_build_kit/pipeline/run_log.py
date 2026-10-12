"""A file per unit run, named for the unit (docs/architecture.md).

The tick prints everything to its own output; this keeps each unit's slice of
it where a person looking for that unit can find it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from agent_build_kit.pipeline.units import Unit
from agent_build_kit.redaction import redact_text

# How many runs of one unit are kept; older ones go when a new one is written.
RUNS_KEPT = 3

# What each further line of a multi-line message starts with, so every line
# that begins at the margin is a new entry and the file stays parsable by line.
CONTINUATION = "    "


# What follows a unit's prefix in a log's name: the run's start stamp and its dash.
_STAMP = r"\d{8}-\d{6}-"
_UNIT_LOG = re.compile(rf"(?P<change>.+)-(?P<number>\d{{2,}})-{_STAMP}")


def run_log_dir(state_dir: Path) -> Path:
    """The directory of its own, under the state directory."""
    return state_dir / "unit-logs"


def tier2_output_dir(state_dir: Path) -> Path:
    """The directory of the full output of each tier 2 run, under the state directory."""
    return state_dir / "tier2-output"


def append_tier2_output(directory: Path, unit: Unit, started: datetime, text: str) -> Path:
    """Append `text` to the unit's file for the tier 2 run begun at `started`, and
    return it. The files of the unit beyond `RUNS_KEPT` are removed first. The file
    is a diagnostic copy, so a write that fails is dropped."""
    path = directory / run_log_name(unit, started, "tier2")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        _prune(directory, unit, keep=RUNS_KEPT - (0 if path.exists() else 1))
        with path.open("a") as file:
            file.write(text)
    except (OSError, ValueError):
        pass
    return path


def _unit_prefix(unit: Unit) -> str:
    number = int(unit.id.rsplit("/", 1)[1])
    return f"{unit.change}-{number:02d}-"


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
        if match and f"{match['change']}/{int(match['number'])}" in summarised:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue
