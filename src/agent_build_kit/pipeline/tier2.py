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
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from pydantic import Field

from agent_build_kit.forges import Forge, RepoId
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.workspaces import process_alive

# Shown on the PR beside the Actions checks.
STATUS_CONTEXT = "local/tier2"

# The config key the tier 2 lock wait is read from; the busy message names it.
LOCK_WAIT_SETTING = "limits.tier2_lock_wait_seconds"

Runner = Callable[[list[str]], str]


class TestFailure(Frozen):
    """One failed or errored test and the first failure line the runner gave it."""

    __test__ = False

    test: str
    line: str


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
    # The file holding the whole output of the run; empty for a result stored without one.
    output_file: str = ""
    # Whether redaction failed on the output, so the file holds the notice in its place.
    output_withheld: bool = False

    @property
    def ok(self) -> bool:
        return self.failed == 0


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
        withheld = " (withheld: redaction failed)" if result.output_withheld else ""
        kept = f"- **Full output:** `{result.output_file}`{withheld}\n"

    return f"""## Tier 2 results

Tier 2 needs the live local stack, so GitHub Actions cannot run it. This ran
on the developer host.

- **Commit tested:** `{result.sha[:7]}`
- **Command:** `{result.command}`
- **Result:** {result.passed} passed, {result.failed} failed, \
{result.skipped} skipped in {result.duration_seconds}s
{failed}{kept}- **Ran against:**
{versions}

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
    forge.post_status(
        repo,
        sha=result.sha,
        ok=result.ok,
        context=STATUS_CONTEXT,
        description=(
            f"{result.passed} passed, {result.failed} failed in {result.duration_seconds:.0f}s"
        ),
        head=head,
    )
