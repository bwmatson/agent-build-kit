"""A plan asked for apart from the store is stored by a second step, with no second planner
call (plan-migration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli.pipeline import apply_planned, plan_apart
from tests.cli.replan_driver import Replan, answer, enable_review, planned, tasks_md

pytestmark = pytest.mark.usefixtures("scripted_engine")

REPLY = answer(
    {**planned("feature/1", (1, 2), lines=300), "review_tier": "light"},
    {**planned("feature/3", (3,), lines=120), "review_tier": "auto"},
)


def shapes(run: Replan) -> list[tuple]:
    return [
        (u.id, u.groups, u.estimated_lines, u.review_tier, u.state, u.depends_on)
        for u in run.store.all()
    ]


def test_an_outcome_applied_stores_what_a_replan_stores_with_one_planner_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(3))
    enable_review(run)
    run.runtime.answer = REPLY

    with plan_apart(run.inst, run.store, ["feature"]) as outcome:
        assert run.store.all() == []
        apply_planned(run.inst, run.store, outcome)
    applied = shapes(run)

    assert run.calls == 1
    assert applied
    assert run.records["feature"]["ok"]
    (run.inst.state_dir / "units.json").unlink()
    (run.inst.state_dir / "planned.json").unlink()
    code, _ = run.run(capsys, "feature")

    assert code == 0
    assert run.calls == 2
    assert shapes(run) == applied
