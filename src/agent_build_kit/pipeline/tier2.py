"""Tier 2: the tests that need the real local stack.

Tier 1 runs anywhere — fakes, fixtures, throwaway containers — and GitHub
Actions runs it on every PR. Tier 2 needs the LLM gateway with a live model,
the browser, the event bus carrying events between services, the router:
the stack as it actually runs on this host, on fixed ports.

There is one of each, so **tier 2 runs are serialized**. Unlike the per-branch
locks, which fail fast because contention there means a scheduling bug, this
lock is a queue: a second unit's tests are perfectly valid, they simply can't
run yet. It waits without a deadline, because failing a unit for queueing is a
fault of the queue, not of the unit; the wait is logged and recorded instead.

Tier 2 gates the push (docs/architecture.md). The order is: tests
pass locally, the branch is pushed, then the status is posted for the commit
that was tested — GitHub only accepts a status for a commit it already has.
A snapshot belongs to one SHA, so a restack invalidates it and tier 2 runs
again.
"""

from __future__ import annotations

import fcntl
import os
import re
import time
from collections.abc import Callable, Collection
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from pydantic import Field

from agent_build_kit import forges
from agent_build_kit.budget import cut_head
from agent_build_kit.config import REST_SPLIT, Tier2Split, active
from agent_build_kit.forges import Forge, RepoId
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.workspaces import process_alive

# Shown on the PR beside the Actions checks.
STATUS_CONTEXT = "local/tier2"


class Tier2Selection(Frozen):
    """What one tier 2 run selects, over a repo's splits: the repo's `marker`, the selectors
    of the splits it requires one of (`any_of`, when `rest` is left out or one split runs
    alone) and those it leaves out (`none_of`), the splits `left_out` and the one that runs
    `only`. `empty` is True when every split, `rest` included, is held and nothing is
    selected. The profile renders it into what its test runner takes."""

    marker: str
    left_out: tuple[str, ...] = ()
    only: str | None = None
    empty: bool = False
    any_of: tuple[str, ...] = ()
    none_of: tuple[str, ...] = ()


def build_selection(
    marker: str,
    splits: Collection[Tier2Split],
    *,
    held: Collection[str] = (),
    only: str | None = None,
) -> Tier2Selection:
    """The selection of a tier 2 run over a repo's declared `splits`: leaving out the `held`
    ones, or running `only` one (a split name or `rest`)."""
    known = [split.name for split in splits]
    for name in [*held, *([only] if only is not None else [])]:
        if name not in known:
            raise ValueError(f"unknown split {name!r} (declared: {', '.join(known)})")
    if only is not None and only in held:
        raise ValueError(f"split {only!r} is asked for alone and also held")
    declared = [split for split in splits if split.marker is not None]
    markers = {split.name: split.marker for split in declared}
    left_out = tuple(sorted(set(held)))
    base = Tier2Selection(marker=marker)
    if only == REST_SPLIT:
        left_out = tuple(split.name for split in declared)
        return base.model_copy(
            update={
                "left_out": left_out,
                "only": only,
                "none_of": tuple(markers[name] for name in left_out),
            }
        )
    if only is not None:
        return base.model_copy(update={"only": only, "any_of": (markers[only],)})
    if REST_SPLIT in left_out:
        kept = tuple(markers[split.name] for split in declared if split.name not in left_out)
        return base.model_copy(update={"left_out": left_out, "any_of": kept, "empty": not kept})
    return base.model_copy(
        update={
            "left_out": left_out,
            "none_of": tuple(markers[s.name] for s in declared if s.name in left_out),
        }
    )


def selection_unavailable(
    toolchain: object,
    *,
    dev_stack_script: bool,
    splits: Collection[Tier2Split],
) -> str | None:
    """Why a tier 2 run of this profile cannot leave a split out, else None. A repo that
    declares no split with a marker is never unable."""
    from agent_build_kit.profiles.base import AppliesTier2Selection

    name = getattr(toolchain, "name", type(toolchain).__name__)
    if not any(split.marker is not None for split in splits):
        return None
    if dev_stack_script:
        return "the repo's dev stack script runs tier 2 and takes no selection"
    kinds = toolchain.selector_kinds if isinstance(toolchain, AppliesTier2Selection) else ()
    if "marker" not in kinds:
        supported = ", ".join(kinds) or "none"
        return f"the {name} profile cannot apply a marker selector (it supports: {supported})"
    return None


# The config key the tier 2 lock wait is read from; the busy message names it.
LOCK_WAIT_SETTING = "global_limits.tier2_lock_wait_seconds"

Runner = Callable[[list[str]], str]

FAILURE_LINE_LIMIT = 500


def clip_failure_line(line: str) -> str:
    """`line` cut with an ellipsis when it is over `FAILURE_LINE_LIMIT`."""
    if len(line) > FAILURE_LINE_LIMIT:
        return line[: FAILURE_LINE_LIMIT - 1] + "…"
    return line


class TestFailure(Frozen):
    """One failed or errored test and the first failure line the runner gave it."""

    __test__ = False

    test: str
    line: str
    # The runtime group the test belongs to (`base` or a runtime's name), `UNKNOWN_GROUP`
    # when it could not be found, empty for a result stored without one.
    group: str = ""


class TestTime(Frozen):
    """The time of one phase (`setup`, `call` or `teardown`) of one test, and where the
    time went when the run said so: agent milliseconds by role with the calls made, the
    scratch pipeline's commands, and the rest. A figure the run did not give is None."""

    __test__ = False

    test: str
    phase: str
    seconds: float
    agent_ms: dict[str, int] = Field(default_factory=dict)
    calls: dict[str, int] = Field(default_factory=dict)
    checks_ms: int | None = None
    other_ms: int | None = None
    overlap: bool = False

    @property
    def has_split(self) -> bool:
        """Whether the run said where this phase's time went: the table shows figures for it
        and its ledger row carries them, and neither does otherwise."""
        return bool(self.agent_ms) or self.checks_ms is not None or self.other_ms is not None


class Tier2Classification(Frozen):
    """A failed run's tests by whose they are: the unit's own, or in a file it left alone."""

    own: list[TestFailure] = Field(default_factory=list)
    untouched: list[TestFailure] = Field(default_factory=list)


class Tier2Verdict(Frozen):
    """What a failed run's tests are once the untouched ones have been run on the base:
    the unit's own, broken by the unit's change, or failing on the base too."""

    own: list[TestFailure] = Field(default_factory=list)
    broken: list[TestFailure] = Field(default_factory=list)
    pre_existing: list[TestFailure] = Field(default_factory=list)
    # The command the base run made and the tail of its output, kept for the record.
    command: str = ""
    base_output: str = ""


class Tier2Result(Frozen):
    sha: str
    passed: int
    failed: int
    skipped: int
    duration_seconds: float
    command: str
    output: str
    stack_versions: dict[str, str] = Field(default_factory=dict)
    failures: list[TestFailure] = Field(default_factory=list)
    # Every phase of every test the run timed, slowest first; empty for a result stored without.
    durations: list[TestTime] = Field(default_factory=list)
    # The file holding the whole output of the run; empty for a result stored without one.
    output_file: str = ""
    # Whether redaction failed on the output, so the file holds the notice in its place.
    output_withheld: bool = False
    # Whether the run ran no test at all because the unit added or changed no tier 2 test.
    ran_no_tests: bool = False
    # The blocked runtimes whose tests this run would have executed and did not.
    parked: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0


# The group of a failed test whose runtime could not be found.
UNKNOWN_GROUP = "unknown"

# What a result that ran no test says in place of its counts, and where a person reads it.
NO_TEST_RAN = "no tier 2 test ran"

# How often a waiter says it is still waiting.
LOCK_LOG_INTERVAL_SECONDS = 300.0


class LockRecord(Frozen):
    """What the holder of the tier 2 lock writes into its file."""

    unit: str
    pid: int
    since: str


def read_lock_record(text: str) -> LockRecord | None:
    """The record in the lock file's text; None when it is empty or not one."""
    try:
        return LockRecord.model_validate_json(text)
    except ValueError:
        return None


def _age(seconds: float) -> str:
    minutes, rest = divmod(int(max(seconds, 0)), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m {rest}s" if hours else f"{minutes}m {rest}s"


def _held_for(record: LockRecord) -> float:
    try:
        return (spans.clock.now() - datetime.fromisoformat(record.since)).total_seconds()
    except ValueError:
        return 0.0


def lock_status_line(path: Path) -> str | None:
    """The `abk status` line for the lock at `path`, None when it is free and has no record.

    Probes the lock with a shared, non-blocking `flock` on a separate open that is released
    at once, reading the record under it when it is free; the file is never created or changed."""
    try:
        handle = path.open("r")
    except FileNotFoundError:
        return None
    with handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            held = True
            record = read_lock_record(handle.read())
        else:
            # Under the shared lock no holder can rewrite the record, so it is read whole.
            held = False
            record = read_lock_record(handle.read())
            fcntl.flock(handle, fcntl.LOCK_UN)
    if record is None:
        return "tier 2: held, holder unknown" if held else None
    if not held:
        return f"tier 2: free (stale record from {record.unit}, process {record.pid} is gone)"
    line = f"tier 2: held by {record.unit} for {_age(_held_for(record))} (since {record.since})"
    if not process_alive(record.pid):
        line += f"; process {record.pid} is gone but the lock is still held"
    return line


def _waiting_message(record: LockRecord | None, waited: float) -> str:
    if record is None:
        return f"tier 2 is busy: waiting for its holder, waited {_age(waited)}"
    message = (
        f"tier 2 is busy: waiting for {record.unit} "
        f"(held for {_age(_held_for(record))}), waited {_age(waited)}"
    )
    if not process_alive(record.pid):
        message += f"; process {record.pid} of {record.unit} is gone but the lock is still held"
    return message


@contextmanager
def stack_lock(
    path: Path,
    timeout: float | None = None,
    setting: str | None = None,
    *,
    holder: str = "",
    on_wait: Callable[[str], None] | None = None,
    on_stale: Callable[[str], None] | None = None,
):
    """Hold the one-and-only tier 2 lock, waiting for it if need be.

    `flock` rather than a PID file: the kernel releases it when the process
    dies, so a crashed run can't wedge the tier for everything after it. `setting`
    names the config key `timeout` came from, so the busy message can say so; a
    `timeout` of None waits without a deadline. While held, the file holds a
    `LockRecord` of `holder`. `on_wait` is told who holds the lock when the wait
    begins and at each interval; `on_stale` is told of a record left by a process
    that is gone.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    began = time.monotonic()
    deadline = None if timeout is None else began + timeout
    next_say = began

    with path.open("a+") as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                now = time.monotonic()
                if deadline is not None and now >= deadline:
                    named = f" ({setting})" if setting else ""
                    raise TimeoutError(
                        f"tier 2 is busy: waited {timeout:.0f}s for {path}{named}"
                    ) from None
                if on_wait is not None and now >= next_say:
                    handle.seek(0)
                    on_wait(_waiting_message(read_lock_record(handle.read()), now - began))
                    next_say = now + LOCK_LOG_INTERVAL_SECONDS
                time.sleep(0.05)

        try:
            handle.seek(0)
            left = read_lock_record(handle.read())
            if left is not None and on_stale is not None and not process_alive(left.pid):
                on_stale(
                    f"tier 2 lock record from {left.unit} (process {left.pid}) is stale, ignored"
                )
            handle.seek(0)
            handle.truncate()
            record = LockRecord(unit=holder, pid=os.getpid(), since=spans.clock.now().isoformat())
            handle.write(record.model_dump_json() + "\n")
            handle.flush()
            yield
        finally:
            handle.truncate(0)
            fcntl.flock(handle, fcntl.LOCK_UN)


COUNTS = re.compile(r"(\d+) (passed|failed|skipped|error)")
DURATION = re.compile(r"in ([\d.]+)s")


def parse_pytest_summary(output: str) -> tuple[int, int, int, float]:
    """(passed, failed, skipped, seconds) from pytest's summary line."""
    counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    for number, label in COUNTS.findall(output):
        counts[label] += int(number)

    duration = DURATION.search(output)
    return (
        counts["passed"],
        counts["failed"] + counts["error"],
        counts["skipped"],
        float(duration.group(1)) if duration else 0.0,
    )


def _split_cells(entry: TestTime) -> str:
    """The agent, checks and other cells of an entry, a dash each when the run gave no split."""
    if not entry.has_split:
        return "- | - | -"
    agent = (
        ", ".join(
            f"{role} {_age(ms / 1000)} x{entry.calls.get(role, 1)}"
            for role, ms in entry.agent_ms.items()
        )
        or "-"
    )
    checks = "-" if entry.checks_ms is None else _age(entry.checks_ms / 1000)
    other = "-" if entry.other_ms is None else _age(entry.other_ms / 1000)
    return f"{agent} | {checks} | {other}{' (overlap)' if entry.overlap else ''}"


def _cell(text: str) -> str:
    """`text` as the content of a markdown table cell: a `|` in it would split the row."""
    return text.replace("|", "\\|")


def _durations_listing(durations: list[TestTime]) -> tuple[str, str]:
    """The line naming the three slowest entries, and the table of the slowest ones, both
    empty when the run timed nothing."""
    if not durations:
        return "", ""
    ranked = sorted(durations, key=lambda e: e.seconds, reverse=True)
    limit = active().global_limits.tier2_durations_shown
    shown = ranked[:limit] if limit else ranked
    head = "; ".join(f"`{e.test}` {e.phase} {_age(e.seconds)}" for e in ranked[:3])
    rows = "\n".join(
        f"| `{_cell(e.test)}` | {e.phase} | {_age(e.seconds)} | {_split_cells(e)} |" for e in shown
    )
    table = (
        f"\n**Time by test** (slowest first, {len(shown)} of {len(ranked)} shown)\n\n"
        "| Test | Phase | Time | Agent | Checks | Other |\n|---|---|---|---|---|---|\n"
        f"{rows}\n"
    )
    return f"- **Slowest:** {head}\n", table


_WITHHELD_NOTE = " (withheld: redaction failed)"
_FULL_OUTPUT = re.compile(r"\*\*Full output:\*\* `([^`]+)`(" + re.escape(_WITHHELD_NOTE) + ")?")


def latest_full_output(feedback: str) -> tuple[str, bool]:
    """The file named by the last "Full output" line of saved feedback and whether that
    output was withheld, or ("", False) when none is named. Each failure is added to the
    feedback already saved, so the last line is the latest run's."""
    found = _FULL_OUTPUT.findall(feedback)
    return (found[-1][0], bool(found[-1][1])) if found else ("", False)


def build_snapshot(result: Tier2Result) -> str:
    """The "Tier 2 results" section of a PR description.

    Tier 2 can't run in CI, so this is the only evidence a reviewer has that it
    ran at all. It names the commit, the command, the counts and the stack it
    ran against, so the claim can be checked rather than taken on trust.
    """
    versions = (
        "\n".join(f"- {name}: `{value}`" for name, value in sorted(result.stack_versions.items()))
        or "- (none recorded)"
    )

    failed = ""
    if result.failures:
        total = result.passed + result.failed + result.skipped
        listing = "\n".join(f"  - `{f.test}` - {f.line}" for f in result.failures)
        failed = f"- **Failed:** {result.failed} of {total} tests\n{listing}\n"

    kept = ""
    if result.output_file:
        withheld = _WITHHELD_NOTE if result.output_withheld else ""
        kept = f"- **Full output:** `{result.output_file}`{withheld}\n"

    slowest, table = _durations_listing(result.durations)
    counts = (
        f"{NO_TEST_RAN}: the unit added or changed none the marker selects"
        if result.ran_no_tests
        else f"{result.passed} passed, {result.failed} failed, "
        f"{result.skipped} skipped in {result.duration_seconds}s"
    )
    if result.parked:
        counts += f"; parked, not run: {', '.join(result.parked)} (not a complete pass)"

    return f"""## Tier 2 results

Tier 2 needs the live local stack, so GitHub Actions cannot run it. This ran
on the developer host.

- **Commit tested:** `{result.sha[:7]}`
- **Command:** `{result.command}`
- **Result:** {counts}
{failed}{kept}{slowest}- **Ran against:**
{versions}
{table}
<details>
<summary>Full output</summary>

```
{result.output}
```

</details>
"""


def post_status(forge: Forge, repo: RepoId, result: Tier2Result, head: str = "") -> None:
    """Publish the tier 2 result as a commit status on the tested SHA.

    Called after the push: a host rejects a status for a commit it has not
    seen. The SHA is the one that was tested, never `HEAD` — those differ the
    moment a restack happens, and a status on the wrong commit is worse than
    none.
    """
    description = (
        f"{result.failed} failed, parked, not run: {', '.join(result.parked)}"
        if result.parked
        else NO_TEST_RAN
        if result.ran_no_tests
        else f"{result.passed} passed, {result.failed} failed in {result.duration_seconds:.0f}s"
    )
    forge.post_status(
        repo,
        sha=result.sha,
        ok=result.ok,
        context=STATUS_CONTEXT,
        description=cut_head(description, forges.status_limit(), "char"),
        head=head,
    )
