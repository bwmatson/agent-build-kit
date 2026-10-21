"""`abk replan` with no arguments adds `stale` and the reason to the state of a stale plan and
keeps its wording and exit status 2 for every other state (plan-migration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.replan_driver import Replan, answer, enable_review, listing, planned, tasks_md

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_the_listing_gives_the_reason_of_a_stale_plan_and_keeps_the_other_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(
        tmp_path, monkeypatch, alpha=tasks_md(1), beta=tasks_md(1), gamma=tasks_md(1), delta="x"
    )
    enable_review(run, ceilings={"full": 750})
    for change in ("alpha", "beta"):
        code, _ = run.run(capsys, change, reply=answer(planned(f"{change}/1", (1,))))
        assert code == 0
    run.record("gamma", ok=False, attempts=1, reason="no reply")
    # delta has a tasks.md the planner never saw.
    enable_review(run, ceilings={"full": 900})
    code, _ = run.run(capsys, "beta", reply=answer(planned("beta/1", (1,))))
    assert code == 0

    lines = listing(run, capsys)

    assert "stale" in lines["alpha"]
    assert "ceilings changed" in lines["alpha"]
    assert lines["beta"].endswith("planned")
    assert lines["delta"].endswith("never planned")
    assert "stale" not in lines["gamma"]
