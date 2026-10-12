"""A plan never closes a cycle with stored work, and a replan leaves started units' edges
alone (spec: unit-scheduling), through `plan_all` and `abk replan` with the planner's
reply in the raw shape a model sends."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import (
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    RUNNING,
    UnitState,
    ready_units,
    waiting_on,
)
from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.factories import unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

SLOTS = {"max_concurrent": 5, "depth_cap": 5}
CYCLE = "checks-add-setting/1 -> checks-hold-unit/2 -> checks-hold-unit/1 -> checks-add-setting/1"


def hold_unit_waiting_on_add_setting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Replan:
    """`checks-hold-unit` is stored, its group 1 needing `checks-add-setting` group 1
    (not planned yet, so not linked) and its unit 2 depending on its unit 1."""
    run = Replan(
        tmp_path,
        monkeypatch,
        **{
            "checks-add-setting": tasks_md(1),
            "checks-hold-unit": tasks_md(2, needs={1: "checks-add-setting group 1"}),
        },
    )
    run.store.upsert(
        [
            unit("checks-hold-unit/1", change="checks-hold-unit", groups=(1,)),
            unit(
                "checks-hold-unit/2",
                change="checks-hold-unit",
                groups=(2,),
                depends_on=("checks-hold-unit/1",),
            ),
        ]
    )
    run.record("checks-hold-unit")
    return run


def test_a_planner_edge_back_into_a_change_that_needs_it_is_dropped_and_the_unit_is_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = hold_unit_waiting_on_add_setting(tmp_path, monkeypatch)
    run.runtime.answer = answer(
        planned("checks-add-setting/1", (1,), depends_on=("checks-hold-unit/2",))
    )

    results = cli.plan_all(run.inst, store=run.store, only={"checks-add-setting"})
    cli.link_needs(run.inst, store=run.store)

    assert results["checks-add-setting"].status == "planned"
    dropped = [line for line in capsys.readouterr().out.splitlines() if CYCLE in line]
    assert len(dropped) == 1
    first = run.store.get("checks-add-setting/1")
    graph = run.store.all()
    assert first.depends_on == ()
    assert waiting_on(first, graph) == []
    assert first in ready_units(graph, **SLOTS)
    assert run.store.get("checks-hold-unit/1").depends_on == ("checks-add-setting/1",)


def test_a_cycle_of_needs_lines_alone_leaves_the_plan_standing_and_a_replan_exits_non_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(
        tmp_path,
        monkeypatch,
        alpha=tasks_md(1, needs={1: "beta group 1"}),
        beta=tasks_md(1, needs={1: "alpha group 1"}),
    )
    run.store.upsert([unit("beta/1", change="beta", groups=(1,))])
    run.record("beta")

    run.runtime.answer = answer(planned("alpha/1", (1,)))
    results = cli.plan_all(run.inst, store=run.store, only={"alpha"}, force=True)

    assert results["alpha"].status == "planned"
    assert results["alpha"].cycle == ("alpha/1", "beta/1", "alpha/1")
    assert run.store.get("alpha/1").depends_on == ()

    code, out = run.run(capsys, "alpha", reply=answer(planned("alpha/1", (1,))))

    assert code != 0
    assert "alpha/1 -> beta/1 -> alpha/1" in out


@pytest.mark.parametrize("state", [RUNNING, IN_REVIEW, FAILED, HELD, MERGED])
def test_a_replan_clears_a_stale_planner_edge_of_an_unstarted_unit_and_not_a_started_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: UnitState
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2), other=tasks_md(1))
    run.store.upsert(
        [
            unit("feature/1", change="feature", groups=(1,), depends_on=("other/1",)),
            unit("feature/2", change="feature", groups=(2,), depends_on=("feature/1",)),
            unit("other/1", change="other", groups=(1,), depends_on=("feature/1",)),
        ]
    )
    run.store.set_state("feature/2", state, branch="spec/feature/2")
    before = run.store.get("feature/1")

    run.runtime.answer = answer(planned("feature/1", (1,), depends_on=("other/1",)))
    cli.plan_all(run.inst, store=run.store, only={"feature"}, force=True)

    after = run.store.get("feature/1")
    assert after.depends_on == ()
    assert (after.state, after.branch) == (before.state, before.branch)
    assert run.store.get("feature/2").depends_on == ("feature/1",)
    assert run.store.get("other/1").depends_on == ("feature/1",)
