"""`abk tags` and `abk status` show the `integration-test` kind as a kind of its own."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import MERGED, PLANNED, UnitState
from tests.cli.replan_driver import Replan, tagged_md
from tests.factories import stored_unit


def test_tags_prints_the_group_as_integration_test_with_no_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tagged_md("unit-test", "integration-test"))

    status = cli.cmd_tags(argparse.Namespace(change="feature", all=False), run.inst)

    out = capsys.readouterr().out
    assert status == 0
    assert "[app] [integration-test] Group 2" in out
    assert "deprecated" not in out


def test_status_shows_the_kind_and_lists_the_unit_with_no_e2e_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tagged_md("integration-test"))
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    UnitStore(run.inst.state_dir / "units.json").upsert(
        [stored_unit("feature/1", change="feature", tier="integration-test")]
    )

    assert cli.cmd_status(argparse.Namespace(), run.inst) == 0

    lines = [re.sub(r"^\[[^\]]*\] ", "", line) for line in capsys.readouterr().out.splitlines()]
    assert [line for line in lines if "feature/1" in line] == [
        "  1. feature/1 (app) — planned order",
        "  feature/1 (app) is integration-test",
    ]


@pytest.mark.parametrize(("state", "shown"), [(PLANNED, True), (MERGED, False)])
def test_status_shows_the_kind_line_only_for_a_unit_that_is_not_finished(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    state: UnitState,
    shown: bool,
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tagged_md("integration-test"))
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    store = UnitStore(run.inst.state_dir / "units.json")
    store.upsert([stored_unit("feature/1", change="feature", tier="integration-test")])
    if state != PLANNED:
        store.set_state("feature/1", state, branch="spec/feature/1")

    assert cli.cmd_status(argparse.Namespace(), run.inst) == 0

    assert ("feature/1 (app) is integration-test" in capsys.readouterr().out) is shown
