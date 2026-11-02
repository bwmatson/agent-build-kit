"""`abk status` says how old each snapshot builds read is, or that it was never collected."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline import snapshots
from agent_build_kit.pipeline.pr_poller import PrState, snapshot, state_path
from tests import fake_clock
from tests.conftest import make_installation, run_status
from tests.usage_host import usage_reading


def snapshot_line(lines: list[str]) -> str:
    (line,) = [line for line in lines if "snapshots:" in line]
    return line


def test_a_kind_nobody_collected_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_clock.install(monkeypatch)
    inst = make_installation(tmp_path / "planning")

    line = snapshot_line(run_status(inst, monkeypatch, capsys))

    assert "pull requests app never collected" in line
    assert "usage default never collected" in line
    assert "pauses never collected" in line


def test_a_stored_value_that_no_longer_validates_shows_as_never_collected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_clock.install(monkeypatch)
    inst = make_installation(tmp_path / "planning")
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    bad = {"value": {"nonsense": True}, "collected_at": fake_clock.START.isoformat()}
    (inst.state_dir / snapshots.STORE).write_text(
        json.dumps({snapshots.USAGE: {"": bad}, snapshots.PAUSES: {"": bad}})
    )

    line = snapshot_line(run_status(inst, monkeypatch, capsys))

    assert "usage default never collected" in line
    assert "pauses never collected" in line


def test_each_kind_held_shows_its_age(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = fake_clock.install(monkeypatch)
    inst = make_installation(tmp_path / "planning")
    pull = PullRequest(number=7, head="spec/feature/1", base="main", state="open")
    PrState.save(state_path(inst.state_dir, "app"), {"7": snapshot(pull)}, "app")
    snapshots.request_refresh(inst.state_dir, snapshots.USAGE, None)
    snapshots.request_refresh(inst.state_dir, snapshots.PAUSES)
    snapshots.run_round(
        inst.state_dir,
        {
            snapshots.USAGE: lambda key: usage_reading(taken=fake_clock.START, resets_in=None),
            snapshots.PAUSES: lambda key: snapshots.Pauses(),
        },
        {},
    )
    clock.advance(timedelta(minutes=3).total_seconds())

    line = snapshot_line(run_status(inst, monkeypatch, capsys))

    assert "pull requests app 3m old" in line
    assert "usage default 3m old" in line
    assert "pauses 3m old" in line
