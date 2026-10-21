"""A dry run prints a refused plan with its reason and the unit ids the planner returned, and
refuses `--forget` (plan-migration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import MERGED
from tests.cli.replan_driver import Replan, answer, enable_review, planned, tasks_md
from tests.factories import stored_unit
from tests.split_sources import snapshot_tree

pytestmark = pytest.mark.usefixtures("scripted_engine")


def merged_group_one(run: Replan) -> None:
    run.store.upsert([stored_unit("feature/1", change="feature", groups=(1,))])
    run.store.set_state("feature/1", MERGED, branch="spec/feature/1")
    run.record("feature")


def test_a_reply_claiming_a_built_group_prints_the_reason_and_the_returned_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))
    enable_review(run)
    merged_group_one(run)
    before = snapshot_tree(run.inst.root)

    code, out = run.run(
        capsys, "feature", "--dry-run", reply=answer(planned("feature/returned", (1, 2)))
    )

    assert code == 1
    assert "group 1" in out
    assert "feature/returned" in out
    assert snapshot_tree(run.inst.root) == before


def test_dry_run_with_forget_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))
    enable_review(run)
    merged_group_one(run)
    before = snapshot_tree(run.inst.root)

    code, out = run.run(capsys, "feature", "--dry-run", "--forget")

    assert code == 2
    assert "--dry-run" in out and "--forget" in out
    assert run.calls == 0
    assert snapshot_tree(run.inst.root) == before
