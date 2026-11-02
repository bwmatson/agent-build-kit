"""The tick's round serves the snapshot requests builds make, under the usage minimum interval.

A request for an account's usage, or a snapshot over the cache lifetime, is answered with one
governed read and cleared; the first round with nothing requested asks the endpoint for nothing
and starts the snapshot from the reading the guard already holds, and a snapshot inside its
limit is left alone. With the guard off, or on a runtime with no usage window, no usage is held
or read. The real guard runs; only the endpoint is faked (`tests/usage_host.py`).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_build_kit.claude_account import Account
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import snapshots
from agent_build_kit.pipeline.pause import pause_marker, pause_until
from agent_build_kit.settings import settings
from tests.conftest import make_installation
from tests.usage_host import Host, called, payload, usage_reading


@pytest.fixture
def inst(tmp_path: Path, host: Host) -> Installation:
    inst = make_installation(tmp_path / "planning", planning={"state_dir": "."})
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host.keep_in(inst.state_dir)
    return inst


def test_a_requested_usage_snapshot_is_read_once_and_the_request_cleared(
    inst: Installation, host: Host
) -> None:
    host.answers = [payload(session=33.0)]
    snapshots.request_refresh(inst.state_dir, snapshots.USAGE, None)

    cli.serve_snapshots(inst)

    assert host.asked == 1
    assert snapshots.requested(inst.state_dir) == []
    held = snapshots.usage(inst.state_dir, None).value
    assert held is not None and held.session_pct == 33


def test_the_first_round_with_nothing_requested_starts_the_snapshot_from_the_held_reading(
    inst: Installation, host: Host
) -> None:
    host.keep_reading(timedelta(minutes=2), payload(session=12.0))

    cli.serve_snapshots(inst)

    assert host.asked == 0
    held = snapshots.usage(inst.state_dir, None).value
    assert held is not None and held.session_pct == 12


def ago(**span: float) -> datetime:
    return datetime.now(UTC) - timedelta(**span)


def test_a_usage_snapshot_inside_its_limit_asks_the_endpoint_for_nothing(
    inst: Installation, host: Host
) -> None:
    snapshots.record(inst.state_dir, snapshots.USAGE, None, usage_reading(12), taken=ago(minutes=1))

    cli.serve_snapshots(inst)

    assert host.asked == 0


def test_an_idle_round_reads_a_usage_snapshot_over_its_limit_once_without_a_request(
    inst: Installation, host: Host
) -> None:
    host.answers = [payload(session=44.0)]
    snapshots.record(inst.state_dir, snapshots.USAGE, None, usage_reading(12), taken=ago(hours=1))

    cli.serve_snapshots(inst)

    assert host.asked == 1
    held = snapshots.usage(inst.state_dir, None).value
    assert held is not None and held.session_pct == 44


def test_a_held_reading_handed_back_while_the_interval_forbids_a_call_keeps_its_age(
    inst: Installation, host: Host
) -> None:
    host.keep_reading(timedelta(minutes=40), payload(session=12.0))
    called(host, timedelta(minutes=1))
    snapshots.record(inst.state_dir, snapshots.USAGE, None, usage_reading(12))
    snapshots.request_refresh(inst.state_dir, snapshots.USAGE, None)

    cli.serve_snapshots(inst)

    assert host.asked == 0
    held = snapshots.usage(inst.state_dir, None)
    assert held.age is not None and held.age > timedelta(minutes=30)
    assert snapshots.requested(inst.state_dir) == []


def test_a_request_for_an_account_the_installation_no_longer_names_is_cleared_unread(
    inst: Installation, host: Host
) -> None:
    snapshots.request_refresh(inst.state_dir, snapshots.USAGE, "/gone/account")

    cli.serve_snapshots(inst)

    assert host.asked == 0
    assert snapshots.requested(inst.state_dir) == []


def test_with_the_guard_off_no_usage_is_held_or_read(
    inst: Installation, host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "usage_guard", "off")
    host.keep_reading(timedelta(minutes=2), payload(session=12.0))
    snapshots.request_refresh(inst.state_dir, snapshots.USAGE, None)

    cli.serve_snapshots(inst)

    assert host.asked == 0
    assert snapshots.usage(inst.state_dir, None).value is None
    assert snapshots.pauses(inst.state_dir).value is not None


def test_on_a_runtime_without_a_usage_window_no_usage_is_held_or_read(
    inst: Installation, host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli.runtimes, "active", lambda: SimpleNamespace(supports_usage_tracking=False)
    )
    host.keep_reading(timedelta(minutes=2), payload(session=12.0))
    snapshots.record(inst.state_dir, snapshots.USAGE, None, usage_reading(12), taken=ago(hours=1))

    cli.serve_snapshots(inst)

    assert host.asked == 0
    held = snapshots.usage(inst.state_dir, None)
    assert held.age is not None and held.age > timedelta(minutes=30)
    assert snapshots.pauses(inst.state_dir).value is not None


def test_a_stored_usage_value_that_no_longer_validates_is_replaced_by_the_round(
    inst: Installation, host: Host
) -> None:
    stale = {"value": {"session_pct": "lots"}, "collected_at": ago(hours=1).isoformat()}
    (inst.state_dir / snapshots.STORE).write_text(json.dumps({"usage": {"": stale}}))
    host.keep_reading(timedelta(minutes=2), payload(session=12.0))

    assert snapshots.usage(inst.state_dir, None).value is None
    cli.serve_snapshots(inst)

    held = snapshots.usage(inst.state_dir, None).value
    assert held is not None and held.session_pct == 12


def test_the_pause_markers_are_collected_every_round(inst: Installation) -> None:
    pause_until(None, reason="usage window", marker=pause_marker(inst.state_dir, Account.default()))
    cli.serve_snapshots(inst)

    found = snapshots.pauses(inst.state_dir).value
    assert found is not None
    assert list(found.resume_at) == ["usage:default"]
