"""The planner is shown a replaced unit of the change it plans as replaced by its successors,
still saying what it built, and an unstarted unit's stored dependency as the resolved list (spec:
a-replaced-unit-points-to-its-successor)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import UnitState
from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.factories import stored_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")


def prompt_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The planner's prompt when change `x` is planned over a store that holds a replaced unit
    of `x`, one of change `y`, and an unstarted unit of `d` that stored a dependency on `x/3`."""
    run = Replan(tmp_path, monkeypatch, x=tasks_md(1), y=tasks_md(3), d=tasks_md(1))
    replaced = {"state": UnitState.UNPLANNED}
    run.store.import_units(
        [
            stored_unit("x/3", change="x", groups=(3,), superseded_by=("x/5",), **replaced),
            stored_unit("x/5", change="x", groups=(3,)),
            stored_unit("y/3", change="y", groups=(3,), superseded_by=("y/5",), **replaced),
            stored_unit("y/5", change="y", groups=(3,)),
            stored_unit("d/1", change="d", groups=(1,), depends_on=("x/3",)),
        ]
    )
    run.runtime.answer = answer(planned("x/5", (1,)))

    cli.plan_all(run.inst, store=run.store, only={"x"})

    return run.runtime.request.prompt.splitlines()


def test_a_replaced_unit_reads_replaced_by_its_successor_and_still_says_what_it_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = prompt_lines(tmp_path, monkeypatch)

    [line] = [line for line in lines if line.startswith("- x/3 ")]
    assert "replaced by x/5" in line
    assert "x group(s) 3" in line


def test_a_replaced_unit_of_another_change_is_not_shown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = prompt_lines(tmp_path, monkeypatch)

    assert not any(line.startswith("- y/3 ") for line in lines)


def test_an_unstarted_unit_is_shown_depending_on_the_successor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = prompt_lines(tmp_path, monkeypatch)

    [line] = [line for line in lines if line.startswith("- d/1 ")]
    assert "depends on x/5" in line
    assert "x/3" not in line
