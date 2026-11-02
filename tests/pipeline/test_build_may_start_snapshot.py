"""A unit's step is gated from the usage snapshot: the build never asks the endpoint.

`build_may_start` is the gate the runner holds for a unit's steps. With the snapshot the round
kept it decides on that reading; with none it refuses as an unknown reading and asks the next
round for one. `host.asked` counts the calls to the endpoint (`tests/usage_host.py`).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_build_kit.pipeline import snapshots
from agent_build_kit.pipeline.snapshots import Request
from agent_build_kit.pipeline.usage_guard import UsageReading, starting
from agent_build_kit.pipeline.wiring import build_may_start, build_resume_at
from tests import fake_clock
from tests.usage_host import Host, configure, pause_at, usage_reading


@pytest.fixture(autouse=True)
def ninety_two(host: Host) -> None:
    configure(**pause_at(92))


def collect(host: Host, value: UsageReading) -> None:
    snapshots.request_refresh(host.cache.parent, snapshots.USAGE, None)
    snapshots.run_round(host.cache.parent, {snapshots.USAGE: lambda key: value}, {})


def test_a_step_is_allowed_on_the_snapshots_reading_without_a_call(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_clock.install(monkeypatch, datetime.now(UTC))
    collect(host, usage_reading(20))

    with starting("feature/1"):
        allowed, _ = build_may_start()()

    assert allowed
    assert host.asked == 0


def test_a_step_is_refused_on_a_full_snapshot_without_a_call(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_clock.install(monkeypatch, datetime.now(UTC))
    collect(host, usage_reading(95))

    with starting("feature/1"):
        allowed, why = build_may_start()()
        resume = build_resume_at()()

    assert not allowed
    assert "session usage at 95%" in why
    assert resume is not None
    assert host.asked == 0


def test_a_step_with_no_snapshot_is_refused_as_unknown_and_asks_the_next_round(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_clock.install(monkeypatch, datetime.now(UTC))

    with starting("feature/1"):
        allowed, why = build_may_start()()

    assert not allowed
    assert "unknown" in why
    assert host.asked == 0
    assert snapshots.requested(host.cache.parent) == [Request(kind="usage", key=None)]
