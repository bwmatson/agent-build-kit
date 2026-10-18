"""`abk status` shows a unit parked for a held e2e-test split and counts it against nothing, and
`abk tick --dry-run` says which parked units it would release (spec: e2e-runtime-parking)."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import PLANNED
from tests.factories import stored_unit
from tests.parked_split_support import Deliveries, hold, installation, park, store_of, stub_round


def status(inst, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> list[str]:
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), inst) == 0
    return capsys.readouterr().out.splitlines()


def test_status_lists_a_parked_unit_with_the_split_the_reason_and_the_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, acp=None)
    deadline = datetime.now(UTC) + timedelta(hours=3)
    hold(inst, "acp", until=deadline)
    park(store_of(inst))

    lines = status(inst, monkeypatch, capsys)

    [waiting] = [line for line in lines if "waiting for e2e-test split acp" in line]
    assert "feature/1" in waiting and "(app)" in waiting
    assert "the usage window is spent" in waiting, "the reason of the hold"
    assert f"{deadline:%Y-%m-%d %H:%M}" in waiting, "and its deadline"


def test_a_hold_with_no_deadline_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, acp=True)
    park(store_of(inst))

    lines = status(inst, monkeypatch, capsys)

    [waiting] = [line for line in lines if "waiting for e2e-test split acp" in line]
    assert "no deadline" in waiting


def test_a_parked_unit_holds_no_place_against_the_unit_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, project_limits={"max_units_in_progress": 1})
    store = store_of(inst)
    park(store)
    store.upsert([stored_unit("fresh/1", change="fresh")])

    lines = status(inst, monkeypatch, capsys)

    assert any("waiting for e2e-test split acp" in line for line in lines)
    assert not any("queue is full" in line for line in lines), "the one place is free"


def test_a_dry_run_says_which_parked_units_would_be_released_and_releases_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, acp=False, claude_code=True)
    stub_round(monkeypatch)
    thread = Deliveries(monkeypatch)
    store = store_of(inst)
    park(store, "usable/1", ("acp",))
    park(store, "held/1", ("claude_code",))
    capsys.readouterr()

    assert cli.cmd_tick(argparse.Namespace(dry_run=True), inst) == 0

    lines = capsys.readouterr().out.splitlines()
    [would] = [line for line in lines if "usable/1" in line and "release" in line]
    assert "would" in would
    assert not any("held/1" in line and "would" in line for line in lines)
    assert thread.delivered == [], "a dry run delivers nothing"
    assert store.get("usable/1").state == PLANNED
