"""A pytest plugin that prints a scratch installation's state with a failed live test.

For a `local_stack` test whose setup, call or teardown failed and that has a scratch (a fixture
argument named `scratch`, or one passed to `register_scratch` during the test), a section named
`SCRATCH STATE` is added to the report, last in the test's failure block. It opens with a
`cause hints:` line and holds the sources of the design, each within its cap, redacted. Git runs
as `runner.run(argv, timeout=GIT_TIMEOUT, ...)` and the redactor is `redactor.redact_text`; a test
replaces either with a stand-in. A source that cannot be read becomes one line,
`scratch state unavailable: <ExceptionType>`, and never changes the test's outcome.

Nothing here writes in the scratch, takes a lock or runs a tick: the reasons are read from the
decision log, the units from `units.json`.
"""

from __future__ import annotations

import json
import subprocess
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import redaction
from agent_build_kit.pipeline.lease import lease_dir
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.pipeline.wait_log import DECISIONS_NAME
from tests.scratch_tick import (
    SECRET_LOOKING,
    Scratch,
    TickResult,
    attempt,
    forget_registered,
    pause_of,
    registered_scratches,
    scratch_env_summary,
    ticks_of,
    unavailable,
    waits_of,
)

# Seconds each `git` command may take.
GIT_TIMEOUT = 10

# The most characters one dump holds, and all the dumps of one session.
DUMP_CHARS = 20480
SESSION_CHARS = 61440

TICK_CHARS = 6000
UNIT_LINES = 20
UNIT_LINE_CHARS = 200
PAUSE_CHARS = 1000
LEASE_LINES = 10
HEAD_LINES = 30
TAIL_LINES = 15
TAIL_LINE_CHARS = 300
REQUEST_LINES = 30
ENV_NAMES = 40

SOURCE = "scratch state"

runner = subprocess
redactor = redaction

_used: pytest.StashKey[int] = pytest.StashKey()
_left_out: pytest.StashKey[int] = pytest.StashKey()


def _last_tick(scratch: Scratch) -> TickResult | None:
    remembered = ticks_of(scratch)
    return remembered[-1] if remembered else None


def _on_remote(scratch: Scratch, branch: str) -> str:
    try:
        found = runner.run(
            ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=scratch.remote,
            capture_output=True,
            timeout=GIT_TIMEOUT,
        )
    except Exception as error:  # noqa: BLE001 — a hint never fails the dump
        return f"{branch} {unavailable('branch state', error)}"
    return f"{branch} is {'on' if found.returncode == 0 else 'not on'} the remote"


def cause_hints(scratch: Scratch, branch: str | None = None, tick: TickResult | None = None) -> str:
    """The `cause hints: ...` line: the last tick's return code, the pause marker, and for a
    `branch` whether it is on the remote and its unit's wait reason. The guarded branch check
    opens with it."""
    tick = tick or _last_tick(scratch)
    parts = [f"tick exited {tick.returncode}" if tick else "no tick was run"]
    if branch:
        parts.append(_on_remote(scratch, branch))
    parts.append(f"pause marker {pause_of(scratch)[0]}")
    if branch:
        unit = "/".join(branch.split("/")[-2:])
        wait = attempt(DECISIONS_NAME, lambda: waits_of(scratch).get(unit, "has no recorded wait"))
        parts.append(f"{unit}: {wait}")
    return "cause hints: " + "; ".join(parts)


def _cut(line: str, size: int) -> str:
    return line[:size]


def _tail(path: Path, lines: int = TAIL_LINES) -> list[str]:
    with path.open() as handle:
        return [_cut(line.rstrip("\n"), TAIL_LINE_CHARS) for line in deque(handle, lines)]


def _tick_output(scratch: Scratch) -> str:
    tick = _last_tick(scratch)
    if tick is None:
        return "no tick was run"
    return f"exited {tick.returncode}\n{tick.output[-TICK_CHARS:]}"


def _reasons(scratch: Scratch) -> str:
    lines = [_cut(f"{unit}: {why}", UNIT_LINE_CHARS) for unit, why in waits_of(scratch).items()]
    return "\n".join(lines[:UNIT_LINES])


def _units(scratch: Scratch) -> str:
    path = scratch.state / "units.json"
    if not path.exists():
        return "(no units.json)"
    lines = []
    for record in json.loads(path.read_text())["units"]:
        last = (record.get("history") or [{}])[-1]
        failure = f" failure={last.get('note', '')} cause={last.get('cause', '')}"
        shown = "" if record.get("state") != "failed" else failure
        lines.append(
            _cut(
                f"{record['id']} state={record.get('state')} branch={record.get('branch')} "
                f"held_by={record.get('held_by')}{shown}",
                UNIT_LINE_CHARS,
            )
        )
    return "\n".join(lines[:UNIT_LINES])


def _pause(scratch: Scratch) -> str:
    return pause_of(scratch)[1][:PAUSE_CHARS]


def _leases(scratch: Scratch) -> str:
    lines = []
    for path in sorted(lease_dir(scratch.state).glob("*.lease")):
        holder = json.loads(path.read_text()).get("holder")
        lines.append(f"{path.stem}: held by {holder}")
    return "\n".join(lines[:LEASE_LINES]) or "(no leases)"


def _heads(scratch: Scratch) -> str:
    found = runner.run(
        ["git", "ls-remote", "--heads", str(scratch.remote)],
        capture_output=True,
        text=True,
        check=True,
        timeout=GIT_TIMEOUT,
    )
    return "\n".join(found.stdout.splitlines()[:HEAD_LINES])


def _decisions(scratch: Scratch) -> str:
    return "\n".join(_tail(scratch.state / DECISIONS_NAME))


def _ledger(scratch: Scratch) -> str:
    rows = [json.loads(line) for line in _tail_raw(scratch.state / LEDGER_NAME)]
    return "\n".join(
        _cut(
            f"{row.get('kind')} {row.get('role')} {row.get('node')} {row.get('duration_ms')}ms",
            TAIL_LINE_CHARS,
        )
        for row in rows
    )


def _tail_raw(path: Path) -> list[str]:
    with path.open() as handle:
        return list(deque(handle, TAIL_LINES))


def _run_log(scratch: Scratch) -> str:
    logs = sorted(
        (scratch.state / "unit-logs").glob("*.log"), key=lambda path: path.stat().st_mtime
    )
    return "\n".join(_tail(logs[-1])) if logs else "(no run log)"


def _requests(scratch: Scratch) -> str:
    host: Any = getattr(scratch, "host", None)
    if host is None:
        return "(no host)"
    return "\n".join(f"{method} {path}" for method, path in host.requests()[:REQUEST_LINES])


def _environment(scratch: Scratch) -> str:
    return "\n".join(scratch_env_summary(scratch.env)[:ENV_NAMES])


ITEMS: tuple[tuple[str, Callable[[Scratch], str]], ...] = (
    ("tick output", _tick_output),
    ("wait reasons", _reasons),
    ("units", _units),
    ("pause marker", _pause),
    ("leases", _leases),
    ("remote heads", _heads),
    ("decision log tail", _decisions),
    ("usage ledger tail", _ledger),
    ("run log tail", _run_log),
    ("host requests", _requests),
    ("tick environment", _environment),
)

WITHHELD = f"{SOURCE} withheld: redaction failed"


def _register_secrets(env: dict[str, str]) -> None:
    for name, value in env.items():
        if SECRET_LOOKING.search(name):
            redactor.register(name, value)


def scratch_state(scratch: Scratch) -> str:
    """The text of the `SCRATCH STATE` section for `scratch`, redacted and within its caps."""
    parts = [attempt(SOURCE, lambda: cause_hints(scratch))]
    for title, read in ITEMS:
        parts.append(f"[{title}]\n" + attempt(SOURCE, lambda read=read: read(scratch)))
    text = "\n".join(parts)
    try:
        _register_secrets(scratch.env)
        text = redactor.redact_text(text, where=SOURCE)
    except Exception:  # noqa: BLE001 — fails closed: no text of the dump is shown
        return WITHHELD
    return text[:DUMP_CHARS]


def _scratch_of(item: pytest.Item) -> Scratch | None:
    if item.get_closest_marker("local_stack") is None:
        return None
    found = (getattr(item, "funcargs", None) or {}).get("scratch")
    if found is not None:
        return found
    registered = registered_scratches()
    return registered[-1] if registered else None


def _section(config: pytest.Config, scratch: Scratch) -> str:
    used = config.stash.get(_used, 0)
    if used >= SESSION_CHARS:
        left = config.stash.get(_left_out, 0) + 1
        config.stash[_left_out] = left
        return (
            f"{SOURCE} dump left out: the session's dumps used {used} characters ({left} left out)"
        )
    text = scratch_state(scratch)
    config.stash[_used] = used + len(text)
    return text


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None):
    forget_registered()
    return (yield)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    report = yield
    try:
        if report.failed:
            scratch = _scratch_of(item)
            if scratch is not None:
                report.sections.append(("SCRATCH STATE", _section(item.config, scratch)))
    except Exception:  # noqa: BLE001 — a hook that cannot report adds nothing
        pass
    return report
