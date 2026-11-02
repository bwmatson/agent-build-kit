"""The tick's round serves the snapshot requests builds make, under the usage minimum interval.

A request for an account's usage is answered with one governed read and cleared; a round with
nothing requested asks the endpoint for nothing and starts the snapshot from the reading the
guard already holds. The real guard runs; only the endpoint is faked (`tests/usage_host.py`).
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.claude_account import Account
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import snapshots
from agent_build_kit.pipeline.pause import pause_marker, pause_until
from tests.conftest import make_installation
from tests.usage_host import Host, payload


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


def test_a_round_with_nothing_requested_asks_the_endpoint_for_nothing(
    inst: Installation, host: Host
) -> None:
    host.keep_reading(timedelta(minutes=2), payload(session=12.0))

    cli.serve_snapshots(inst)

    assert host.asked == 0
    held = snapshots.usage(inst.state_dir, None).value
    assert held is not None and held.session_pct == 12


def test_the_pause_markers_are_collected_every_round(inst: Installation) -> None:
    pause_until(None, reason="usage window", marker=pause_marker(inst.state_dir, Account.default()))
    cli.serve_snapshots(inst)

    found = snapshots.pauses(inst.state_dir).value
    assert found is not None
    assert list(found.resume_at) == ["usage:default"]
