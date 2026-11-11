"""A file per unit run, named for the unit (docs/architecture.md).

The tick prints everything to its own output; this keeps each unit's slice of
it where a person looking for that unit can find it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Collection, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import overload

from agent_build_kit.compat_names import moved_to_current_name, old_spelling
from agent_build_kit.model import Frozen, TestTier
from agent_build_kit.orchestration.artifacts import Artifacts
from agent_build_kit.orchestration.local.directories import (
    E2E_OUTPUTS,
    FAILURE_BUNDLES,
    RUN_LOGS,
)
from agent_build_kit.orchestration.local.directories import (
    failure_bundles_dir as failure_bundles_dir,
)
from agent_build_kit.orchestration.local.directories import run_log_dir as run_log_dir
from agent_build_kit.pipeline.artifact_scope import append_redacted, scoped
from agent_build_kit.pipeline.file_lock import file_lock
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


_OUTPUT_DIR = E2E_OUTPUTS

# The name the directory had under the kind's old spelling.
_OLD_OUTPUT_DIR = f"{old_spelling(TestTier.E2E_TEST)}-output"


def adopt_old_e2e_output(state_dir: Path) -> Path:
    """Move the e2e-test output directory left under the old name to the current one, and
    return the current one."""
    return moved_to_current_name(state_dir, _OUTPUT_DIR, _OLD_OUTPUT_DIR)


def e2e_output_dir(state_dir: Path) -> Path:
    """The directory of the full output of each e2e-test run, under the state directory. One
    left under the old name is moved to the current one first."""
    return adopt_old_e2e_output(state_dir)


@overload
def append_e2e_output(target: Path, unit: Unit, started: datetime, text: str) -> Path: ...


@overload
def append_e2e_output(target: Artifacts, unit: Unit, started: datetime, text: str) -> str: ...


def append_e2e_output(
    target: Artifacts | Path, unit: Unit, started: datetime, text: str
) -> Path | str:
    """Append `text` to the unit's output for the e2e-test run begun at `started`, and return
    where it is (the key; the file when given a directory). The unit's outputs beyond
    `RUNS_KEPT` are removed first. The output is a diagnostic copy, so a write that fails is
    dropped."""
    store, folder = scoped(target, _OUTPUT_DIR)
    key = f"{folder}{run_log_name(unit, started, 'e2e-test')}"
    try:
        _prune(store, folder, unit, keep=RUNS_KEPT - (0 if store.list(key) else 1))
        append_redacted(store, key, text)  # the caller redacts the chunk as a whole
    except (OSError, ValueError):
        pass
    return target / key.rsplit("/", 1)[1] if isinstance(target, Path) else key


# The most of a failing run's output a bundle keeps, in bytes.
FAILURE_OUTPUT_CAP = 5_000_000


# The size a ledger of unit-test runs reaches before it is rotated, in bytes.
TEST_RUNS_MAX_BYTES = 1_000_000


def run_ledger_path(state_dir: Path) -> Path:
    """The ledger of every unit-test run, one JSON row each, under the state directory."""
    return state_dir / "test-runs.jsonl"


class FailedTest(Frozen):
    """A failed test of a ledger row: the worker that ran it, None when the output does not say,
    and whether its failure is the test's own time limit."""

    test: str
    worker: str | None = None
    time_limit: bool = False
    # Whether the test errored after the first time-limit hit of its worker: a consequence of it.
    consequence: bool = False


class TestRun(Frozen):
    """One row of the ledger of unit-test runs: what ran and under what conditions, no output."""

    __test__ = False  # not a test class, whatever pytest makes of the name

    unit: str
    # The run's start, an ISO 8601 time.
    started: str
    seconds: float
    # `passed`, `failed` (also when the failure is not the unit's), `flake` or `disturbed` (the
    # machine was suspended in the run, so its failures were not judged).
    outcome: str
    failed: list[str]
    # The one-minute load average at the start and end, when the machine says.
    load_start: float | None
    load_end: float | None
    # What the test command asked for (a count or `auto`), when it says.
    workers: str | None
    tick: str
    units_running: list[str]
    # How long the run waited for a unit-test slot (`global_limits.max_concurrent_unit_tests`)
    # before it started; `seconds` and the load readings are of the run after the wait.
    wait_seconds: float = 0.0
    # The host's CPU count and whether its load at the start or end was at or above
    # `tests.load_high_per_cpu` for each CPU; None on a row written before, or when the host
    # does not say.
    cpus: int | None = None
    load_high: bool | None = None
    # The worker and time-limit hit of each test of `failed`.
    failed_detail: list[FailedTest] = []
    # For a `disturbed` run: how many seconds its wall time exceeded the duration pytest reported.
    disturbed_seconds: float | None = None
    # Where the run's selection data came from: `base`, `own` or `none`; and for `base` the age of
    # the recording in hours.
    data_source: str | None = None
    data_age_hours: float | None = None


def append_test_run(path: Path, run: TestRun, *, max_bytes: int = TEST_RUNS_MAX_BYTES) -> None:
    """Add `run` to the ledger at `path`; a ledger already `max_bytes` long is moved to
    `<name>.1` (replacing an older one) first."""
    with file_lock(path.with_suffix(".lock")):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size >= max_bytes:
            path.replace(path.with_name(path.name + ".1"))
        with path.open("a", encoding="utf-8") as handle:
            handle.write(run.model_dump_json() + "\n")


@overload
def write_failure_bundle(
    target: Path,
    unit_id: str,
    change: str,
    started: datetime,
    *,
    output: str,
    context: Mapping[str, object],
    machine: Mapping[str, object],
    worktree: Mapping[str, object],
    pointed: Collection[Path | str] = (),
    cap: int = FAILURE_OUTPUT_CAP,
) -> Path: ...


@overload
def write_failure_bundle(
    target: Artifacts,
    unit_id: str,
    change: str,
    started: datetime,
    *,
    output: str,
    context: Mapping[str, object],
    machine: Mapping[str, object],
    worktree: Mapping[str, object],
    pointed: Collection[Path | str] = (),
    cap: int = FAILURE_OUTPUT_CAP,
) -> str: ...


def write_failure_bundle(
    target: Artifacts | Path,
    unit_id: str,
    change: str,
    started: datetime,
    *,
    output: str,
    context: Mapping[str, object],
    machine: Mapping[str, object],
    worktree: Mapping[str, object],
    pointed: Collection[Path | str] = (),
    cap: int = FAILURE_OUTPUT_CAP,
) -> Path | str:
    """Save a failing unit-test run as the keys under `<unit prefix><stamp>/` and return the
    bundle (its key; the folder when given a directory): `output.txt` (redacted, cut at `cap`
    bytes with a note), `context.json`, `machine.json` and `worktree.json` (redacted). The
    unit's bundles beyond `RUNS_KEPT` go, except those in `pointed`. The bundle is a diagnostic
    copy, so a write that fails is dropped."""
    store, folder = scoped(target, FAILURE_BUNDLES)
    name = f"{unit_file_prefix(unit_id, change)}{started:%Y%m%d-%H%M%S}"
    text = redact_text(output, where="failure bundle")
    encoded = text.encode()
    if len(encoded) > cap:
        text = (
            encoded[:cap].decode(errors="ignore")
            + f"\n[output cut at {cap} bytes; {len(encoded) - cap} more were dropped]\n"
        )
    try:
        _write_evidence(store, f"{folder}{name}", text, context, machine, worktree)
        _prune_bundles(store, folder, unit_file_prefix(unit_id, change), pointed)
    except (OSError, ValueError):
        pass
    return target / name if isinstance(target, Path) else f"{folder}{name}"


def write_rerun_evidence(
    target: Artifacts | Path,
    bundle: Path | str,
    number: int,
    *,
    output: str,
    context: Mapping[str, object],
    machine: Mapping[str, object],
    worktree: Mapping[str, object],
) -> None:
    """Save serial rerun `number` of a failing run under `<bundle>/reruns/<number>/`: its
    redacted `output.txt`, `context.json`, `machine.json` and `worktree.json`. A diagnostic
    copy, so a write that fails is dropped."""
    store, folder = scoped(target, FAILURE_BUNDLES)
    try:
        _write_evidence(
            store,
            f"{folder}{_last(bundle)}/reruns/{number}",
            redact_text(output, where="failure bundle"),
            context,
            machine,
            worktree,
        )
    except (OSError, ValueError):
        pass


def _last(place: Path | str) -> str:
    """The last segment of a bundle, whether it is named by a key or by a path."""
    return str(place).rstrip("/").rsplit("/", 1)[-1]


def _write_evidence(
    store: Artifacts,
    folder: str,
    output: str,
    context: Mapping[str, object],
    machine: Mapping[str, object],
    worktree: Mapping[str, object],
) -> None:
    """Write the four files of a run's evidence into `folder`: `output.txt` as given (already
    redacted and cut) and the three fact files, redacted here."""
    store.put(f"{folder}/output.txt", output.encode())
    for name, facts in (("context", context), ("machine", machine), ("worktree", worktree)):
        body = redact_text(json.dumps(facts, indent=2, default=str), where="failure bundle")
        store.put(f"{folder}/{name}.json", body.encode())


def _prune_bundles(
    store: Artifacts, folder: str, prefix: str, pointed: Collection[Path | str]
) -> None:
    """Remove the unit's bundles beyond the newest `RUNS_KEPT`, except those pointed at."""
    keep = {f"{folder}{_last(place)}" for place in pointed}
    named = re.compile(re.escape(folder + prefix) + r"\d{8}-\d{6}(?=/)")
    bundles = sorted({m[0] for key in store.list(folder + prefix) if (m := named.match(key))})
    for old in bundles[:-RUNS_KEPT]:
        if old not in keep:
            store.delete(f"{old}/")


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
        target: Artifacts | Path,
        unit: Unit,
        *,
        step: str,
        model: str,
        base: str,
        started: datetime,
        report: Callable[[str], None] = lambda message: None,
    ) -> None:
        self._name = run_log_name(unit, started, step)
        self._store, folder = scoped(target, RUN_LOGS)
        self._key = f"{folder}{self._name}"
        self._report = report
        self._working = True
        try:
            self._store.put(
                self._key,
                f"unit: {unit.id}\nchange: {unit.change}\nstep: {step}\nmodel: {model}\n"
                f"base: {base}\nstarted: {started.isoformat()}\n\n",
            )
            _prune(self._store, folder, unit)
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
            append_redacted(self._store, self._key, text)  # `emit` redacted it as a whole
        except (OSError, ValueError) as error:
            self._failed(error)

    def emit(self, message: str) -> None:
        message = redact_text(message, where="run log")
        first, *rest = message.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self._append("".join(f"{line}\n" for line in [first, *(CONTINUATION + r for r in rest)]))

    def close(self, outcome: str) -> None:
        self._append(f"\noutcome: {outcome}\n")


def _unit_logs(store: Artifacts, folder: str, prefix: str) -> list[str]:
    """The keys of the unit whose prefix this is: a stamp follows it directly,
    so a change whose name merely begins with another's is not matched."""
    pattern = re.compile(re.escape(folder + prefix) + _STAMP)
    return sorted(key for key in store.list(folder + prefix) if pattern.match(key))


def _prune(store: Artifacts, folder: str, unit: Unit, *, keep: int = RUNS_KEPT) -> None:
    for key in _unit_logs(store, folder, _unit_prefix(unit))[: -keep or None]:
        store.delete(key)


def remove_change_logs(target: Artifacts | Path, change: str, folder: str = RUN_LOGS) -> None:
    """Drop every unit log of a change under `folder` (the unit logs unless said otherwise).
    The logs are a diagnostic copy: a store that cannot be read leaves the archive it follows
    standing."""
    store, folder = scoped(target, folder)
    try:
        for key in store.list(folder):
            if (match := _UNIT_LOG.match(key.removeprefix(folder))) and match["change"] == change:
                store.delete(key)
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
