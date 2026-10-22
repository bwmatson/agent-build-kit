"""A replan of a partly started change keeps the started units whole and reshapes only the
planned ones (plan-migration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, PLANNED, UnitState
from tests.cli.replan_driver import Replan, answer, enable_review, planned, tasks_md
from tests.factories import stored_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

OLD_SIZING = "a-digest-of-other-ceilings"


def test_started_units_are_kept_whole_and_only_the_planned_two_take_the_new_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(4))
    enable_review(run)
    run.store.upsert(
        [stored_unit(f"feature/{n}", change="feature", groups=(n,)) for n in (1, 2, 3, 4)]
    )
    run.store.set_state("feature/1", MERGED, branch="spec/feature/1", pr=5)
    run.store.set_state("feature/2", IN_REVIEW, branch="spec/feature/2", pr=6)
    run.record("feature", sizing=OLD_SIZING)
    merged, in_review = run.store.get("feature/1"), run.store.get("feature/2")

    code, out = run.run(
        capsys, "feature", "--accept-unplanned", reply=answer(planned("feature/3", (3, 4)))
    )

    assert code == 0
    assert run.calls == 1
    assert run.store.get("feature/1") == merged
    assert run.store.get("feature/2") == in_review
    assert f"kept: feature/1, {MERGED.value}" in out
    assert f"kept: feature/2, {IN_REVIEW.value}" in out
    prompt = run.runtime.requests[0].prompt
    assert "built by feature/1" in prompt and "built by feature/2" in prompt
    assert run.store.get("feature/3").groups == (3, 4)
    assert run.store.get("feature/3").state == PLANNED
    assert run.store.get("feature/4").state == UnitState.UNPLANNED
