"""What live tests share to run `abk tick` in a scratch installation and read a unit's branch."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

import pytest

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.pause import PAUSE_MARKER
from agent_build_kit.pipeline.wait_log import DECISIONS_NAME, ENDED
from agent_build_kit.redaction import redact_text
from tests.factories import git, who_pushed
from tests.usage_condition import skip_on_usage_condition

# The program a tick runs, replaceable by a test that stands in for it.
ABK: Path = Path(sys.executable).parent / "abk"

# Seconds each `git` command of a diagnostic may take, and the module that runs it, which a
# test replaces with a stand-in.
GIT_TIMEOUT = 10
runner = subprocess

# How many ticks of one scratch are remembered.
KEPT_TICKS = 3

# Lines of the run log a failure shows.
RUN_LOG_LINES = 30

SECRET_LOOKING = re.compile("TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL|AUTH")


class Scratch(Protocol):
    """What the helpers need of a live test's scratch installation."""

    @property
    def planning(self) -> Path: ...

    @property
    def remote(self) -> Path: ...

    @property
    def state(self) -> Path: ...

    @property
    def env(self) -> dict[str, str]: ...


class TickResult(Frozen):
    """One `abk tick`: its return code, its output lines with the second each arrived at."""

    returncode: int
    lines: tuple[tuple[float, str], ...]
    started: float
    ended: float

    @property
    def output(self) -> str:
        return "\n".join(text for _, text in self.lines)


_TICKS: dict[Path, deque[TickResult]] = {}
_REGISTERED: list[Scratch] = []


def run_tick(scratch: Scratch, *, timeout: float = 3600) -> TickResult:
    """`abk tick` as a process in the scratch, stamping each output line as it arrives, and
    remembered as one of the scratch's last ticks."""
    started = time.monotonic()
    lines: list[tuple[float, str]] = []
    process = subprocess.Popen(
        [str(ABK), "tick"],
        cwd=scratch.planning,
        env=scratch.env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    def read() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.append((time.monotonic(), line.rstrip("\n")))

    reader = threading.Thread(target=read)
    reader.start()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        raise
    finally:
        reader.join()
    result = TickResult(
        returncode=returncode, lines=tuple(lines), started=started, ended=time.monotonic()
    )
    _TICKS.setdefault(scratch.state, deque(maxlen=KEPT_TICKS)).append(result)
    return result


def ticks_of(scratch: Scratch) -> tuple[TickResult, ...]:
    """The last three ticks run in `scratch`, oldest first."""
    return tuple(_TICKS.get(scratch.state, ()))


def scratch_env_summary(env: Mapping[str, str]) -> list[str]:
    """One line for each environment variable: `NAME=value` through the redactor, or the name
    alone when it looks like a secret."""
    return [
        name
        if SECRET_LOOKING.search(name)
        else redact_text(f"{name}={value}", where="scratch environment")
        for name, value in env.items()
    ]


def unavailable(source: str, error: Exception) -> str:
    """The one line a diagnostic shows for a source it could not read."""
    return f"{source} unavailable: {type(error).__name__}"


def attempt(source: str, read: Callable[[], str]) -> str:
    """`read()`, or the one line naming why `source` could not be read."""
    try:
        return read()
    except Exception as error:  # noqa: BLE001 — a diagnostic never hides the others
        return unavailable(source, error)


def waits_of(scratch: Scratch) -> dict[str, str]:
    """Each unit's latest wait reason from the decision log, with what it waits on."""
    latest: dict[str, str] = {}
    for line in (scratch.state / DECISIONS_NAME).read_text().splitlines():
        record = json.loads(line)
        if record["reason"] == ENDED:
            latest.pop(record["unit"], None)
            continue
        waiting = f", waits on {', '.join(record['waits_on'])}" if record.get("waits_on") else ""
        latest[record["unit"]] = f"{record['reason']}{waiting}"
    return latest


def pause_of(scratch: Scratch) -> tuple[str, str]:
    """The pause marker's status (`absent`, `present` or `unreadable`) and what to show of it."""
    marker = scratch.state / PAUSE_MARKER
    try:
        if not marker.exists():
            return "absent", "absent"
        return "present", marker.read_text().strip()
    except Exception as error:  # noqa: BLE001 — a diagnostic never hides the others
        return "unreadable", unavailable(marker.name, error)


def newest_run_log(scratch: Scratch) -> Path | None:
    """The run log written last in the scratch's state directory, or None when there is none."""
    logs = sorted(
        (scratch.state / "unit-logs").glob("*.log"), key=lambda path: path.stat().st_mtime
    )
    return logs[-1] if logs else None


def _run_log(scratch: Scratch) -> str:
    newest = newest_run_log(scratch)
    if newest is None:
        return "(no run log)"
    return "\n".join(newest.read_text().splitlines()[-RUN_LOG_LINES:])


def branch_on_remote(scratch: Scratch, branch: str) -> bool:
    """Whether `branch` is on the scratch's remote."""
    found = runner.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=scratch.remote,
        capture_output=True,
        timeout=GIT_TIMEOUT,
    )
    return found.returncode == 0


def _on_remote(scratch: Scratch, branch: str) -> str:
    def probe() -> str:
        return f"{branch} is {'on' if branch_on_remote(scratch, branch) else 'not on'} the remote"

    return attempt(f"{branch} on the remote", probe)


def cause_hints(scratch: Scratch, branch: str | None = None, tick: TickResult | None = None) -> str:
    """The `cause hints: ...` line: the last tick's return code, the pause marker, and for a
    `branch` whether it is on the remote and its unit's wait reason. The guarded branch check and
    the failure dump both open with it."""
    if tick is None:
        remembered = ticks_of(scratch)
        tick = remembered[-1] if remembered else None
    parts = [f"tick exited {tick.returncode}" if tick else "no tick was run"]
    if branch:
        parts.append(_on_remote(scratch, branch))
    parts.append(f"pause marker {pause_of(scratch)[0]}")
    if branch:
        unit = "/".join(branch.split("/")[-2:])
        wait = attempt(DECISIONS_NAME, lambda: waits_of(scratch).get(unit, "has no recorded wait"))
        parts.append(f"{unit}: {wait}")
    return "cause hints: " + "; ".join(parts)


def _pushes(scratch: Scratch) -> list[str]:
    return [
        line
        for path in (scratch.state / "unit-logs").glob("*.log")
        for line in path.read_text().splitlines()
        if "git push" in line or " pushed spec/" in line
    ]


def _failure(scratch: Scratch, branch: str, tick: TickResult | None) -> str:
    _, pause = pause_of(scratch)
    sections = [
        cause_hints(scratch, branch, tick),
        "--- tick output ---\n" + (tick.output if tick else "no tick was run"),
        "--- wait reasons ---\n"
        + attempt(DECISIONS_NAME, lambda: json.dumps(waits_of(scratch), indent=1)),
        "--- run log ---\n" + attempt("run log", lambda: _run_log(scratch)),
        "--- pause marker ---\n" + pause,
        attempt("push history", lambda: who_pushed(scratch.remote, branch, _pushes(scratch))),
    ]
    return "\n".join(sections)


def commits_on_unit_branch(
    scratch: Scratch, branch: str, tick: TickResult | None = None
) -> list[str]:
    """The ids of the commits `branch` has over `main` on the scratch's remote. A branch that
    never arrived fails the test with cause hints, the tick's output and the scratch's state,
    not with a git error. `tick` defaults to the last one run in the scratch."""
    try:
        return git(scratch.remote, "log", "--format=%H", f"main..{branch}").split()
    except subprocess.CalledProcessError:
        pass
    # Outside the handler, so the failure is not shown chained to a git error.
    skip_on_usage_condition(scratch, branch)
    remembered = ticks_of(scratch)
    pytest.fail(_failure(scratch, branch, tick or (remembered[-1] if remembered else None)))


def register_scratch(scratch: Scratch) -> None:
    """Make `scratch` the one the failure dump of the running test reads, for a test that builds
    its scratch inside a helper and so has none as a fixture argument."""
    _REGISTERED.append(scratch)


def registered_scratches() -> tuple[Scratch, ...]:
    """The scratches registered since `forget_registered` was last called."""
    return tuple(_REGISTERED)


def forget_registered() -> None:
    """Start a test with no registered scratch."""
    _REGISTERED.clear()
