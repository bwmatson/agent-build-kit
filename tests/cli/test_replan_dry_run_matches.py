"""A dry run prints the units a replan then stores, each asking the planner once
(plan-migration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.replan_driver import Replan, answer, enable_review, planned, tasks_md

pytestmark = pytest.mark.usefixtures("scripted_engine")

REPLY = answer(
    {**planned("feature/left", (1, 2), lines=300), "review_tier": "light"},
    {**planned("feature/right", (3,), lines=120), "review_tier": "auto"},
)


def test_the_units_a_dry_run_prints_are_the_units_a_replan_stores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(3))
    enable_review(run)

    dry_code, dry_out = run.run(capsys, "feature", "--dry-run", reply=REPLY)
    assert dry_code == 0
    assert run.calls == 1
    assert run.store.all() == []

    code, _ = run.run(capsys, "feature")
    stored = run.store.all()

    assert code == 0
    assert run.calls == 2
    assert {unit.id for unit in stored} == {"feature/left", "feature/right"}
    for unit in stored:
        line = next(line for line in dry_out.splitlines() if unit.id in line)
        assert str(unit.estimated_lines) in line
        assert (unit.review_tier or "") in line
        assert ", ".join(str(n) for n in unit.groups) in line
