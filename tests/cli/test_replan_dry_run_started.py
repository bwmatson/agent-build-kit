"""A dry run prints the started units it leaves alone and the joins in the plan
(plan-migration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import IN_REVIEW, MERGED
from tests.cli.replan_driver import Replan, answer, enable_review, planned, tasks_md
from tests.factories import stored_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")


def line_with(out: str, *words: str) -> str:
    return next(line for line in out.splitlines() if all(word in line for word in words))


def test_started_units_are_printed_as_kept_and_only_the_rest_is_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(4))
    enable_review(run)
    run.store.upsert([stored_unit(f"feature/{n}", change="feature", groups=(n,)) for n in (1, 2)])
    run.store.set_state("feature/1", MERGED, branch="spec/feature/1")
    run.store.set_state("feature/2", IN_REVIEW, branch="spec/feature/2")
    run.record("feature")

    code, out = run.run(capsys, "feature", "--dry-run", reply=answer(planned("feature/3", (3, 4))))

    assert code == 0
    assert run.calls == 1
    assert "kept" in line_with(out, "feature/1", MERGED.value)
    assert "kept" in line_with(out, "feature/2", IN_REVIEW.value)
    assert "built by feature/1" in run.runtime.requests[0].prompt
    assert "built by feature/2" in run.runtime.requests[0].prompt
    assert "would be stored" in line_with(out, "feature/3")
    assert "would be stored" not in line_with(out, "feature/1")
    assert "would be stored" not in line_with(out, "feature/2")


def test_a_join_is_printed_with_the_unit_it_is_added_to_and_the_estimate_before_and_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1), other=tasks_md(2))
    run.store.upsert([stored_unit("feature/1", change="feature", groups=(1,), estimated_lines=100)])
    run.record("feature")
    run.record("other")
    join = {"onto": "feature/1", "change": "other", "groups": [1], "estimated_lines": 40}

    code, out = run.run(
        capsys, "other", "--dry-run", reply=answer(planned("other/2", (2,)), joins=[join])
    )

    assert code == 0
    line = line_with(out, "join", "feature/1")
    assert "100" in line and "140" in line
    assert run.store.get("feature/1").estimated_lines == 100
