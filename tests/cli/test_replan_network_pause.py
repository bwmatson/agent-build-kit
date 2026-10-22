"""A replan that meets a network outage records the network pause in the real state directory,
and a dry run records none (plan-migration)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.pipeline.pause import RESUME_GRACE
from agent_build_kit.pipeline.unit_store import PARK_BACKOFF
from tests.cli.plan_outage_fakes import network, raises
from tests.cli.replan_driver import Replan, tasks_md
from tests.fake_clock import install

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Replan:
    install(monkeypatch)
    replan = Replan(tmp_path, monkeypatch, feature=tasks_md(1))
    replan.runtime.act = raises(network())
    return replan


def test_a_replan_that_meets_a_network_outage_writes_the_network_pause(
    run: Replan, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = run.run(capsys, "feature")

    assert code == 1
    pause = json.loads((run.inst.state_dir / "paused.json").read_text())
    assert pause["kind"] == "network"
    assert "feature" in pause["reason"]


def test_the_real_pause_ends_when_the_planning_wrote_it_to_end_with_no_grace_added_again(
    run: Replan, capsys: pytest.CaptureFixture[str]
) -> None:
    before = datetime.now(UTC)

    run.run(capsys, "feature")

    after = datetime.now(UTC)
    until = datetime.fromisoformat(
        json.loads((run.inst.state_dir / "paused.json").read_text())["until"]
    )
    # The backoff and the grace once, as a tick writes for the same outage, not the grace twice.
    assert until >= before + PARK_BACKOFF[0] + RESUME_GRACE
    assert until <= after + PARK_BACKOFF[0] + RESUME_GRACE


def test_a_dry_run_that_meets_a_network_outage_writes_no_pause(
    run: Replan, capsys: pytest.CaptureFixture[str]
) -> None:
    run.run(capsys, "feature", "--dry-run")

    assert not (run.inst.state_dir / "paused.json").exists()
