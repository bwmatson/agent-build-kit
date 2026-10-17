"""A pytest plugin that prints a scratch installation's state with a failed live test.

For a `local_stack` test whose setup, call or teardown failed and that has a scratch, a section
named `SCRATCH STATE` is added to the report, last in the test's failure block. The scratch is
found, in this order, as a fixture argument named `scratch`, as the `scratch` attribute of any
fixture argument (a module-scoped fixture that builds one and hands its tick on), or as the one
passed to `register_scratch` during the test. The section opens with a `cause hints:` line and
holds the sources of the design, each within its cap, redacted. Git runs through
`scratch_tick.runner` with `scratch_tick.GIT_TIMEOUT`, and the redactor is
`redactor.redact_text`; a test replaces either with a stand-in. A source that cannot be read
becomes one line, `scratch state unavailable: <ExceptionType>`, and never changes the test's
outcome.

Nothing here writes in the scratch, takes a lock or runs a tick: the reasons are read from the
decision log, the units from `units.json`, the e2e lock's holder from its file.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import redaction
from agent_build_kit.model import E2E_LOCK_FILE
from agent_build_kit.pipeline.e2e import read_lock_record
from agent_build_kit.pipeline.lease import lease_dir
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.pipeline.wait_log import DECISIONS_NAME
from tests import scratch_tick
from tests.scratch_tick import (
    SECRET_LOOKING,
    Scratch,
    attempt,
    cause_hints,
    forget_registered,
    newest_run_log,
    pause_of,
    registered_scratches,
    scratch_env_summary,
    ticks_of,
    waits_of,
)

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

# The states of a unit that may have a branch worth asking about.
OPEN_STATES = ("planned", "held", "failed")

SOURCE = "scratch state"

redactor = redaction

_used: pytest.StashKey[int] = pytest.StashKey()
_left_out: pytest.StashKey[int] = pytest.StashKey()


def _cut(line: str, size: int) -> str:
    return line[:size]


def _tail_raw(path: Path) -> list[str]:
    with path.open() as handle:
        return list(deque(handle, TAIL_LINES))


def _tail(path: Path) -> list[str]:
    return [_cut(line.rstrip("\n"), TAIL_LINE_CHARS) for line in _tail_raw(path)]


def _tick_output(scratch: Scratch) -> str:
    remembered = ticks_of(scratch)
    if not remembered:
        return "no tick was run"
    tick = remembered[-1]
    return f"exited {tick.returncode}\n{tick.output[-TICK_CHARS:]}"


def _reasons(scratch: Scratch) -> str:
    lines = [_cut(f"{unit}: {why}", UNIT_LINE_CHARS) for unit, why in waits_of(scratch).items()]
    return "\n".join(lines[:UNIT_LINES])


def _stored_units(scratch: Scratch) -> list[StoredUnit] | None:
    """The units in `units.json` as the store reads them, without taking its lock; None when
    there is no file."""
    path = scratch.state / "units.json"
    if not path.exists():
        return None
    return [StoredUnit.model_validate(record) for record in json.loads(path.read_text())["units"]]


def _units(scratch: Scratch) -> str:
    units = _stored_units(scratch)
    if units is None:
        return "(no units.json)"
    lines = []
    for unit in units:
        failure = f" failure={unit.note} cause={unit.cause}" if unit.state == "failed" else ""
        shown = f"{unit.id} state={unit.state} branch={unit.branch} held_by={unit.held_by}"
        lines.append(_cut(shown + failure, UNIT_LINE_CHARS))
    return "\n".join(lines[:UNIT_LINES])


def _hint_branch(scratch: Scratch) -> str | None:
    """The branch of the first planned, held or failed unit that has one; None when the units
    cannot be read."""
    try:
        return next(
            (u.branch for u in _stored_units(scratch) or [] if u.state in OPEN_STATES and u.branch),
            None,
        )
    except Exception:  # noqa: BLE001 — a hint never fails the dump
        return None


def _pause(scratch: Scratch) -> str:
    return pause_of(scratch)[1][:PAUSE_CHARS]


def _leases(scratch: Scratch) -> str:
    lines = []
    for path in sorted(lease_dir(scratch.state).glob("*.lease")):
        holder = json.loads(path.read_text()).get("holder")
        lines.append(f"{path.stem}: held by {holder}")
    return "\n".join(lines[:LEASE_LINES]) or "(no leases)"


def _e2e_lock(scratch: Scratch) -> str:
    """The holder the lock file records, read without the lock itself."""
    path = scratch.state / E2E_LOCK_FILE
    if not path.exists():
        return "(no e2e lock)"
    record = read_lock_record(path.read_text())
    if record is None:
        return "(the e2e lock file holds no record)"
    return f"held by unit {record.unit}, pid {record.pid}, since {record.since}"


def _heads(scratch: Scratch) -> str:
    found = scratch_tick.runner.run(
        ["git", "ls-remote", "--heads", str(scratch.remote)],
        capture_output=True,
        text=True,
        check=True,
        timeout=scratch_tick.GIT_TIMEOUT,
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


def _run_log(scratch: Scratch) -> str:
    newest = newest_run_log(scratch)
    return "\n".join(_tail(newest)) if newest else "(no run log)"


def _requests(scratch: Scratch) -> str:
    host: Any = getattr(scratch, "host", None)
    if host is None:
        return "(no host)"
    return "\n".join(f"{method} {path}" for method, path in host.requests()[-REQUEST_LINES:])


def _environment(scratch: Scratch) -> str:
    return "\n".join(scratch_env_summary(scratch.env)[:ENV_NAMES])


ITEMS: tuple[tuple[str, Callable[[Scratch], str]], ...] = (
    ("tick output", _tick_output),
    ("wait reasons", _reasons),
    ("units", _units),
    ("pause marker", _pause),
    ("leases", _leases),
    ("e2e lock", _e2e_lock),
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
    parts = [attempt(SOURCE, lambda: cause_hints(scratch, _hint_branch(scratch)))]
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
    funcargs = getattr(item, "funcargs", None) or {}
    if funcargs.get("scratch") is not None:
        return funcargs["scratch"]
    for value in funcargs.values():
        try:
            held = getattr(value, "scratch", None)
        except Exception:  # noqa: BLE001 — a property that raises is not a scratch
            continue
        if held is not None and hasattr(held, "state"):
            return held
    registered = registered_scratches()
    return registered[-1] if registered else None


def _section(config: pytest.Config, scratch: Scratch) -> str:
    """The dump, or one line saying it was left out when it would take the session past
    `SESSION_CHARS`. Only what is printed is counted."""
    used = config.stash.get(_used, 0)
    text = scratch_state(scratch)
    if used + len(text) > SESSION_CHARS:
        left = config.stash.get(_left_out, 0) + 1
        config.stash[_left_out] = left
        text = f"{SOURCE} dump left out: the session's budget is spent ({left} left out)"
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
