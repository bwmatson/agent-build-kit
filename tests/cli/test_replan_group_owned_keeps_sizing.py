"""A plan refused because another unit owns a group keeps the policy digest of the plan that
stands, so the change still reads as stale (plan-migration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import PLANNED
from tests.cli.replan_driver import Replan, answer, enable_review, planned, tasks_md
from tests.factories import stored_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

OLD_SIZING = "a-digest-of-other-ceilings"


def test_a_group_owned_refusal_leaves_the_change_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))
    enable_review(run)
    run.store.upsert([stored_unit("feature/1", change="feature", groups=(1, 2))])
    run.store.set_state("feature/1", PLANNED, branch="spec/feature/1")
    run.record("feature", sizing=OLD_SIZING)
    split = answer(planned("feature/a", (1,)), planned("feature/b", (2,)))

    code, _ = run.run(capsys, "feature", reply=split)

    assert code == 1
    record = run.records["feature"]
    assert record["ok"] is False
    assert record["sizing"] == OLD_SIZING
    assert cli.plan_is_stale(record)
