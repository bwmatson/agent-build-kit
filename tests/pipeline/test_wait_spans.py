"""A usage-paused unit reads as paused wherever a state is shown, with its stored state
unchanged (spec: unit-timeline-is-recorded). A review round's span cause is driven through
the graph in `tests/graph/test_round_causes.py`."""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.pause import PAUSE_MARKER, pause_until
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import RUNNING
from agent_build_kit.pipeline.vocabulary import effective_state, state_label
from tests.conftest import make_installation
from tests.factories import new_unit, stored_unit


def running_unit(tmp_path: Path) -> tuple[Installation, UnitStore]:
    inst = make_installation(
        tmp_path, planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")}
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([new_unit("feature/1")])
    store.set_state("feature/1", RUNNING, branch="spec/feature/1")
    return inst, store


def pause(inst: Installation, kind: str = "usage") -> None:
    pause_until(
        spans.clock.now() + timedelta(hours=2),
        reason="session usage at 90%",
        marker=inst.state_dir / PAUSE_MARKER,
        kind=kind,  # type: ignore[arg-type]
    )


def test_a_usage_paused_unit_displays_as_paused_with_its_stored_state_unchanged() -> None:
    unit = stored_unit(state=RUNNING, branch="spec/add-marker/1")

    assert effective_state(unit, [unit], usage_paused=True) == "paused"
    assert effective_state(unit, [unit]) == RUNNING
    assert unit.state == RUNNING


def test_paused_is_a_state_with_a_label() -> None:
    label = state_label("paused")

    assert label is not None
    assert label.name == "paused"


def test_the_graph_page_draws_a_running_unit_as_paused_while_a_pause_is_in_force(
    tmp_path: Path,
) -> None:
    inst, store = running_unit(tmp_path)
    pause(inst)

    assert cli.cmd_graph(argparse.Namespace(), inst) == 0

    page = inst.graph_page.read_text()
    assert "class feature_1 paused" in page
    assert store.get("feature/1").state == RUNNING


def test_the_graph_page_draws_it_as_running_once_the_pause_is_over(tmp_path: Path) -> None:
    inst, _store = running_unit(tmp_path)

    cli.cmd_graph(argparse.Namespace(), inst)

    assert "class feature_1 running" in inst.graph_page.read_text()
