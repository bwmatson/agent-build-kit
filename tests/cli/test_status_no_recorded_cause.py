"""`abk status` lists a unit in flight that has no cause, and not one a replan left a cause on."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import HELD, PLANNED
from tests.conftest import make_installation
from tests.factories import unit
from tests.standing_causes import REPLANS, replan

CHANGE = "a"


def test_status_lists_a_held_and_a_started_planned_unit_whose_history_has_no_cause(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = cli.store_for(make_installation(tmp_path))
    store.upsert([unit("a/1"), unit("a/2"), unit("a/3")], change=CHANGE)
    store.set_state("a/1", HELD, note="held before the cause was kept")
    store.set_state("a/2", PLANNED, note="rework requested: x", branch="spec/a/2")
    capsys.readouterr()

    cli.cmd_status(argparse.Namespace(), make_installation(tmp_path))

    text = "".join(capsys.readouterr())
    assert "no recorded cause: a/1, a/2" in text


@pytest.mark.parametrize("how", REPLANS)
def test_status_does_not_list_a_started_unit_a_replan_kept_a_cause_on_nor_an_unstarted_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], how: str
) -> None:
    graph = [unit("a/1"), unit("a/2"), unit("a/3")]
    store = cli.store_for(make_installation(tmp_path))
    store.upsert(graph, change=CHANGE)
    store.set_state("a/1", HELD, note="held before the cause was kept")
    store.set_state("a/2", PLANNED, note="based on an old base", branch="spec/a/2")
    store.set_state("a/2", PLANNED, note="the base moved", cause=Cause.BASE_CHANGED)
    replan(store, how, graph, change=CHANGE)
    capsys.readouterr()

    cli.cmd_status(argparse.Namespace(), make_installation(tmp_path))

    text = "".join(capsys.readouterr())
    assert "no recorded cause: a/1\n" in text
    assert "a/2" not in text.split("no recorded cause")[1].split("\n")[0]
    assert "a/3" not in text.split("no recorded cause")[1].split("\n")[0]
