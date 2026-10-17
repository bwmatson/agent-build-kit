"""A pytest plugin that splits a e2e-test test's time by agent role, checks and the rest.

For each phase (setup, call, teardown) of a `local_stack` test that requests the
`scratch_ledger` fixture, a path to the scratch installation's usage ledger, the plugin reads
the rows appended since the last phase that used that ledger, so a module fixture's rows fall
in the setup of the first test using it. At the end of the session it prints one line per
phase: the prefix `ABK-TIME` and JSON with the test id, the phase, agent milliseconds and
calls by role, the commands' milliseconds (`checks_ms`), the remainder of the phase's wall time
(`other_ms`, never negative) and `overlap`, true when the parts sum above the wall time.
The e2e-test result reads these lines; a test without the fixture gets none.

The phase's wall time is read from `clock.monotonic()`; a test replaces `clock` with one it moves.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline.e2e_times import SPLIT_PREFIX

clock = time

LEDGER_FIXTURE = "scratch_ledger"

_lines: pytest.StashKey[list[dict[str, Any]]] = pytest.StashKey()
_offsets: pytest.StashKey[dict[Path, int]] = pytest.StashKey()


def _rows_since(path: Path, offset: int) -> tuple[list[dict[str, Any]], int]:
    """The ledger's whole lines after byte `offset`, skipping any that are not JSON objects,
    and the offset after them."""
    if not path.exists():
        return [], offset
    with path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read()
    whole = data[: data.rfind(b"\n") + 1]
    rows: list[dict[str, Any]] = []
    for line in whole.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows, offset + len(whole)


def _split(
    item: pytest.Item, phase: str, rows: list[dict[str, Any]], wall_ms: int
) -> dict[str, Any]:
    agent: dict[str, int] = {}
    calls: dict[str, int] = {}
    checks_ms = 0
    for row in rows:
        ms = int(row.get("duration_ms") or 0)
        if row.get("kind") == "agent":
            role = str(row.get("role", ""))
            agent[role] = agent.get(role, 0) + ms
            calls[role] = calls.get(role, 0) + 1
        elif row.get("kind") == "span" and row.get("command"):
            checks_ms += ms
    parts = sum(agent.values()) + checks_ms
    return {
        "test": item.nodeid,
        "phase": phase,
        "agent": agent,
        "calls": calls,
        "checks_ms": checks_ms,
        "other_ms": max(0, wall_ms - parts),
        "overlap": parts > wall_ms,
    }


def _ledger(item: pytest.Item) -> Path | None:
    if item.get_closest_marker("local_stack") is None:
        return None
    found = (getattr(item, "funcargs", None) or {}).get(LEDGER_FIXTURE)
    return Path(found) if found is not None else None


def _measured(item: pytest.Item, phase: str):
    """Run the rest of a hook and record its split, whether or not it raised."""
    started = clock.monotonic()
    before = _ledger(item)
    try:
        return (yield)
    finally:
        wall_ms = round((clock.monotonic() - started) * 1000)
        path = _ledger(item) or before
        if path is not None:
            offsets = item.config.stash.setdefault(_offsets, {})
            rows, offsets[path] = _rows_since(path, offsets.get(path, 0))
            item.config.stash.setdefault(_lines, []).append(_split(item, phase, rows, wall_ms))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item: pytest.Item):
    return (yield from _measured(item, "setup"))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item):
    return (yield from _measured(item, "call"))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item):
    return (yield from _measured(item, "teardown"))


def pytest_terminal_summary(terminalreporter: Any, config: pytest.Config) -> None:
    for line in config.stash.get(_lines, []):
        terminalreporter.write_line(SPLIT_PREFIX + json.dumps(line))
