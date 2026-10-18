"""A retired unit is shown as retired and finished, and as nothing in progress, by the graph,
the status and the units listing (spec: a-started-unit-keeps-its-groups)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.diagram import render_mermaid
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.vocabulary import (
    FINISHED,
    STATES,
    effective_state,
)
from tests.conftest import make_installation
from tests.factories import stored_unit

RETIRED = UnitState.RETIRED


def test_retired_is_finished_and_has_a_style_of_its_own() -> None:
    assert RETIRED in FINISHED
    style = STATES[RETIRED]
    assert style.name == "retired"
    unplanned = STATES[UnitState.UNPLANNED]
    assert (style.fill, style.stroke, style.text) != (
        unplanned.fill,
        unplanned.stroke,
        unplanned.text,
    )


def test_the_diagram_draws_a_retired_unit_in_the_retired_style() -> None:
    gone = stored_unit("feat/1", state=RETIRED, branch="spec/feat/1")

    diagram = render_mermaid([gone])

    assert effective_state(gone, [gone]) == "retired"
    assert "classDef retired " in diagram
    assert "class feat_1 retired" in diagram
    assert "· retired" in diagram


def test_the_status_a_listing_reads_for_a_retired_unit_is_a_state_the_graph_knows() -> None:
    gone = stored_unit("feat/1", state=RETIRED, branch="spec/feat/1")

    assert effective_state(gone, [gone]) in STATES


def test_status_counts_a_retired_unit_as_retired_and_holding_no_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = make_installation(
        tmp_path,
        planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees")),
        project_limits={"max_units_in_progress": 1},
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("feat/1"), stored_unit("feat/2")])
    store.set_state("feat/1", RETIRED, branch="spec/feat/1")
    monkeypatch.setattr(cli, "current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), workspace) == 0

    out = capsys.readouterr().out
    units_line = next(line for line in out.splitlines() if "] units: " in line)
    assert "1 retired" in units_line
    assert "queue is full" not in out, "the retired unit holds no place"
