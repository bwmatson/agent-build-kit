"""A step's usage decision is made from the account's snapshot, never from the endpoint.

The round collects the reading; the guard reads it with its age. A reading older than its
limit records a refresh request and is judged by the guard's rule for an old reading
(spec: snapshots). Only the endpoint and the home directory are faked (`tests/usage_host.py`),
and `host.asked` counts the calls made to the endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline import snapshots
from agent_build_kit.pipeline.snapshots import Request
from agent_build_kit.pipeline.usage_guard import (
    Decision,
    UsageReading,
    decide_start,
    rate_limit_note,
    snapshot_reading,
    starting,
)
from tests import fake_clock
from tests.usage_host import Host, configure, pause_at, refused, usage_reading

HOUR = timedelta(hours=1)
LIMIT = 10 * timedelta(minutes=1)


@pytest.fixture(autouse=True)
def ninety_two(host: Host) -> None:
    configure(**pause_at(92))


def reading(session: int, *, taken: datetime, source: str) -> UsageReading:
    return usage_reading(session, taken=taken, source=source)


def collect(state_dir: Path, value: UsageReading) -> None:
    """The round collects `value` as the default account's reading."""
    snapshots.request_refresh(state_dir, snapshots.USAGE, None)
    snapshots.run_round(state_dir, {snapshots.USAGE: lambda key: value}, {snapshots.USAGE: LIMIT})


def step_decision() -> Decision:
    """The decision a unit's step asks for: a start named for a unit."""
    with starting("feature/1"):
        return decide_start(from_snapshot=True)


def state_of(host: Host) -> Path:
    return host.cache.parent


def test_a_fresh_snapshot_under_the_threshold_allows_a_start_without_a_call(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = fake_clock.install(monkeypatch, datetime.now(UTC))
    collect(state_of(host), reading(20, taken=clock.now(), source="live"))
    clock.advance(30)

    decision = step_decision()

    assert decision.may_start
    assert host.asked == 0
    assert snapshots.requested(state_of(host)) == []


def test_a_fresh_snapshot_over_the_threshold_refuses_a_start_without_a_call(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = fake_clock.install(monkeypatch, datetime.now(UTC))
    collect(state_of(host), reading(95, taken=clock.now(), source="live"))
    clock.advance(30)

    decision = step_decision()

    assert not decision.may_start
    assert host.asked == 0
    assert snapshots.requested(state_of(host)) == []


def test_a_snapshot_over_its_limit_asks_for_a_refresh_and_is_judged_as_an_old_reading(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = fake_clock.install(monkeypatch, datetime.now(UTC) - 2 * HOUR)
    collect(state_of(host), reading(20, taken=clock.now(), source="live"))
    clock.advance(2 * HOUR.total_seconds())

    decision = step_decision()

    assert not decision.may_start
    assert "stale" in decision.reason
    assert host.asked == 0
    assert snapshots.requested(state_of(host)) == [Request(kind="usage", key=None)]


def test_a_snapshot_inside_its_limit_whose_window_has_reset_is_not_refused_on_its_old_percent(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = fake_clock.install(monkeypatch, datetime.now(UTC) - timedelta(minutes=3))
    full = reading(95, taken=clock.now(), source="live")
    # The session window it describes ended a minute ago; the snapshot is three minutes old.
    full = full.model_copy(update={"resets_at": datetime.now(UTC) - timedelta(minutes=1)})
    collect(state_of(host), full)
    clock.advance(180)
    stored = snapshots.usage(state_of(host), None)
    assert stored.age is not None and stored.age < timedelta(minutes=5)

    decision = step_decision()

    assert "95%" not in decision.reason
    assert host.asked == 0
    assert snapshots.requested(state_of(host)) == [Request(kind="usage", key=None)]


def test_a_reading_stored_with_a_rate_limit_note_carries_only_the_note_in_force(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = fake_clock.install(monkeypatch, datetime.now(UTC))
    stored = "cache (rate limited until 14:05)"
    collect(state_of(host), usage_reading(95, taken=clock.now(), source=stored))
    host.keep_reading(timedelta(minutes=1))
    refused(host, cooling=timedelta(minutes=10))
    note = rate_limit_note()
    assert note

    cooling = snapshot_reading()

    assert cooling is not None
    assert cooling.source == f"cache ({note})"

    host.keep_reading(timedelta(minutes=1))
    assert rate_limit_note() is None

    ended = snapshot_reading()

    assert ended is not None
    assert ended.source == "cache"


def test_no_snapshot_asks_for_a_refresh_and_is_judged_as_an_unknown_reading(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_clock.install(monkeypatch, datetime.now(UTC))

    decision = step_decision()

    assert not decision.may_start
    assert "unknown" in decision.reason
    assert host.asked == 0
    assert snapshots.requested(state_of(host)) == [Request(kind="usage", key=None)]
