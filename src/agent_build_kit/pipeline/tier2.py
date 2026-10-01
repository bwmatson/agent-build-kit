"""Tier 2: the tests that need the real local stack.

Tier 1 runs anywhere — fakes, fixtures, throwaway containers — and GitHub
Actions runs it on every PR. Tier 2 needs the LLM gateway with a live model,
the browser, the event bus carrying events between services, the router:
the stack as it actually runs on this host, on fixed ports.

There is one of each, so **tier 2 runs are serialized**. Unlike the per-branch
locks, which fail fast because contention there means a scheduling bug, this
lock is a queue: a second unit's tests are perfectly valid, they simply can't
run yet. It waits, with a timeout, because an unattended run that blocks
forever is indistinguishable from a crashed one and holds its worktree the
whole time.

Tier 2 gates the push (docs/architecture.md). The order is: tests
pass locally, the branch is pushed, then the status is posted for the commit
that was tested — GitHub only accepts a status for a commit it already has.
A snapshot belongs to one SHA, so a restack invalidates it and tier 2 runs
again.
"""

from __future__ import annotations

import fcntl
import re
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from pydantic import Field

from agent_build_kit.forges import Forge, RepoId
from agent_build_kit.model import Frozen

# Shown on the PR beside the Actions checks.
STATUS_CONTEXT = "local/tier2"

# Long enough for a queue of real tier 2 runs to drain, short enough that a
# wedged run surfaces the same day.
DEFAULT_LOCK_TIMEOUT_SECONDS = 3600

Runner = Callable[[list[str]], str]


class Tier2Result(Frozen):
    sha: str
    passed: int
    failed: int
    skipped: int
    duration_seconds: float
    command: str
    output: str
    stack_versions: dict[str, str] = Field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.failed == 0


@contextmanager
def stack_lock(path: Path, timeout: float = DEFAULT_LOCK_TIMEOUT_SECONDS):
    """Hold the one-and-only tier 2 lock, waiting for it if need be.

    `flock` rather than a PID file: the kernel releases it when the process
    dies, so a crashed run can't wedge the tier for everything after it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout

    with path.open("a+") as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"tier 2 is busy: waited {timeout:.0f}s for {path}"
                    ) from None
                time.sleep(0.05)

        try:
            handle.seek(0)
            handle.truncate()
            handle.write(f"held since {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n")
            handle.flush()
            yield
        finally:
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

    return f"""## Tier 2 results

Tier 2 needs the live local stack, so GitHub Actions cannot run it. This ran
on the developer host.

- **Commit tested:** `{result.sha[:7]}`
- **Command:** `{result.command}`
- **Result:** {result.passed} passed, {result.failed} failed, \
{result.skipped} skipped in {result.duration_seconds}s
- **Ran against:**
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
