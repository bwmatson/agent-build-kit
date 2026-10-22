"""`--stale` beside another selector does not call a change skipped that the other selector
plans (plan-migration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.replan_driver import Replan, answer, enable_review, planned, tasks_md

pytestmark = pytest.mark.usefixtures("scripted_engine")

OLD_SIZING = "a-digest-of-other-ceilings"


def test_failed_with_stale_plans_a_given_up_change_without_calling_it_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, bravo=tasks_md(1))
    enable_review(run)
    run.record(
        "bravo",
        sizing=OLD_SIZING,
        ok=False,
        attempts=run.inst.max_plan_attempts,
        reason="the graph call failed",
    )

    code, out = run.run(capsys, "--stale", "--failed", reply=answer(planned("bravo/1", (1,))))

    assert code == 0
    assert {unit.change for unit in run.store.all()} == {"bravo"}
    assert "skipped" not in out
