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
from agent_build_kit.redaction import redact_text
from tests.factories import git, who_pushed

# The program a tick runs, replaceable by a test that stands in for it.
ABK: Path = Path(sys.executable).parent / "abk"

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


def _attempt(source: str, read: Callable[[], str]) -> str:
    try:
        return read()
    except Exception as error:  # noqa: BLE001 — a diagnostic never hides the others
        return f"{source} unavailable: {type(error).__name__}"


def _waits(scratch: Scratch) -> dict[str, str]:
    """Each unit's latest wait reason from the decision log, with what it waits on."""
    latest: dict[str, str] = {}
    for line in (scratch.state / "decisions.jsonl").read_text().splitlines():
        record = json.loads(line)
        waiting = f", waits on {', '.join(record['waits_on'])}" if record.get("waits_on") else ""
        latest[record["unit"]] = f"{record['reason']}{waiting}"
    return {unit: wait for unit, wait in latest.items() if not wait.startswith("none")}


def _pause(scratch: Scratch) -> str:
    marker = scratch.state / "paused.json"
    return marker.read_text().strip() if marker.exists() else "absent"


def _run_log(scratch: Scratch) -> str:
    logs = sorted(
        (scratch.state / "unit-logs").glob("*.log"), key=lambda path: path.stat().st_mtime
    )
    if not logs:
        return "(no run log)"
    return "\n".join(logs[-1].read_text().splitlines()[-RUN_LOG_LINES:])


def _pushes(scratch: Scratch) -> list[str]:
    return [
        line
        for path in (scratch.state / "unit-logs").glob("*.log")
        for line in path.read_text().splitlines()
        if "git push" in line or " pushed spec/" in line
    ]


def _failure(scratch: Scratch, branch: str, tick: TickResult | None) -> str:
    unit = "/".join(branch.split("/")[-2:])
    pause = _attempt("paused.json", lambda: _pause(scratch))
    marker = (
        "absent" if pause == "absent" else "unreadable" if "unavailable" in pause else "present"
    )
    wait = _attempt("decisions.jsonl", lambda: _waits(scratch).get(unit, "has no recorded wait"))
    ran = f"tick exited {tick.returncode}" if tick else "no tick was run"
    sections = [
        f"cause hints: {ran}; {branch} is not on the remote; pause marker {marker}; {unit}: {wait}",
        "--- tick output ---\n" + (tick.output if tick else "no tick was run"),
        "--- wait reasons ---\n"
        + _attempt("decisions.jsonl", lambda: json.dumps(_waits(scratch), indent=1)),
        "--- run log ---\n" + _attempt("run log", lambda: _run_log(scratch)),
        "--- pause marker ---\n" + pause,
        _attempt("push history", lambda: who_pushed(scratch.remote, branch, _pushes(scratch))),
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
        remembered = ticks_of(scratch)
        pytest.fail(_failure(scratch, branch, tick or (remembered[-1] if remembered else None)))
