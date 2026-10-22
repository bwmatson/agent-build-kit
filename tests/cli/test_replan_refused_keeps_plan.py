"""A refused or failed replan leaves the stored units alone, says the old plan stands, and the
change still reads as stale (plan-migration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import MERGED
from tests.cli.replan_driver import Replan, answer, enable_review, listing, planned, tasks_md
from tests.factories import stored_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

OLD_SIZING = "a-digest-of-other-ceilings"
# Group 1 is built by a merged unit, so the checks refuse a plan that carries it again.
REFUSED = answer(planned("feature/a", (1,)), planned("feature/b", (2,)))


def stale_with_a_merged_unit(run: Replan, **record: object) -> None:
    run.store.upsert([stored_unit("feature/1", change="feature", groups=(1,))])
    run.store.set_state("feature/1", MERGED, branch="spec/feature/1")
    run.record("feature", sizing=OLD_SIZING, **record)


def test_a_refused_plan_keeps_the_units_and_the_old_digest_and_uses_an_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))
    enable_review(run)
    stale_with_a_merged_unit(run)
    before = run.store.all()

    code, out = run.run(capsys, "feature", reply=REFUSED)

    assert code == 1
    assert "group 1" in out
    assert "the old plan stands" in out
    assert run.store.all() == before
    record = run.records["feature"]
    assert record["attempts"] == 1
    assert record["sizing"] == OLD_SIZING
    assert cli.plan_is_stale(record)


def test_a_change_that_has_used_every_attempt_is_given_up_and_named_for_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))
    enable_review(run)
    last = run.inst.max_plan_attempts - 1
    stale_with_a_merged_unit(run, attempts=last, ok=False, reason="an earlier refusal")

    run.run(capsys, "feature", reply=REFUSED)

    record = run.records["feature"]
    assert record["attempts"] == run.inst.max_plan_attempts
    assert record["sizing"] == OLD_SIZING
    line = listing(run, capsys)["feature"]
    assert "given up" in line and "--failed" in line
