"""A replan that would leave units `unplanned` lists them and applies nothing for that change
until `--accept-unplanned` is given (plan-migration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import PLANNED, UnitState
from agent_build_kit.runtimes import AgentRequest
from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.factories import stored_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

ONE_UNIT = answer(planned("feature/1", (1, 2, 3)))


def three_planned(run: Replan, change: str = "feature") -> None:
    run.store.upsert([stored_unit(f"{change}/{n}", change=change, groups=(n,)) for n in (1, 2, 3)])
    run.record(change)


def line_with(out: str, *words: str) -> str:
    return next(line for line in out.splitlines() if all(word in line for word in words))


def test_a_plan_that_drops_units_lists_them_and_stores_nothing_without_the_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(3))
    three_planned(run)
    before = run.store.all()

    code, out = run.run(capsys, "feature", reply=ONE_UNIT)

    assert code == 1
    assert run.calls == 1
    for uid in ("feature/2", "feature/3"):
        assert "group" in line_with(out, uid, PLANNED.value)
    assert "--accept-unplanned" in out
    assert run.store.all() == before


def test_with_the_flag_the_plan_is_stored_and_the_dropped_units_are_unplanned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(3))
    three_planned(run)

    code, _ = run.run(capsys, "feature", "--accept-unplanned", reply=ONE_UNIT)

    assert code == 0
    assert run.calls == 1
    assert run.store.get("feature/1").groups == (1, 2, 3)
    assert run.store.get("feature/2").state == UnitState.UNPLANNED
    assert run.store.get("feature/3").state == UnitState.UNPLANNED


def test_two_changes_are_decided_apart_one_applied_and_one_held_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(
        tmp_path,
        monkeypatch,
        alpha=tasks_md(3).replace("Group", "Ay work"),
        beta=tasks_md(3).replace("Group", "Bee work"),
    )
    three_planned(run, "alpha")
    three_planned(run, "beta")
    replies = {
        "Ay work": answer(planned("alpha/1", (1, 2, 3))),
        "Bee work": answer(
            planned("beta/1", (1,), lines=120), planned("beta/2", (2,)), planned("beta/3", (3,))
        ),
    }

    def reply_by_change(request: AgentRequest) -> None:
        run.runtime.answer = next(text for key, text in replies.items() if key in request.prompt)

    run.runtime.act = reply_by_change
    alpha_before = [unit for unit in run.store.all() if unit.change == "alpha"]

    code, out = run.run(capsys, "alpha", "beta")

    assert code == 1
    assert run.calls == 2
    assert [unit for unit in run.store.all() if unit.change == "alpha"] == alpha_before
    assert "alpha/2" in out
    assert run.store.get("beta/1").estimated_lines == 120
    assert all(unit.state == PLANNED for unit in run.store.all() if unit.change == "beta")
