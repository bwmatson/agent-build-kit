"""A tick reports a stale plan and neither plans it nor counts it as work (plan-staleness)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.cli.replan_driver import Replan, answer, planned, tasks_md, tick, ticking_replan
from tests.factories import unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

OLD_SIZING = "a-digest-of-other-ceilings"


def run_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, feature: str, other: str = ""
) -> Replan:
    changes = {"feature": feature, **({"other": other} if other else {})}
    return ticking_replan(tmp_path, monkeypatch, changes)


def test_a_stale_plan_is_not_planned_is_named_and_is_not_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = run_in(tmp_path, monkeypatch, tasks_md(1))
    run.record("feature", sizing=OLD_SIZING)

    assert not cli.has_work(run.inst, run.store), "a stale plan alone is no work"

    # Something else in progress makes the tick run, so what it says is heard.
    run.store.upsert([unit("other/1", change="other", groups=(1,))])
    run.store.set_state("other/1", IN_REVIEW, pr=5, branch="spec/other/1")
    code, out = tick(run, capsys)

    assert code == 0
    assert run.calls == 0
    stale = next(line for line in out.splitlines() if "stale" in line)
    assert "feature" in stale
    assert "abk replan" in stale
    assert run.records["feature"]["sizing"] == OLD_SIZING


def test_an_edited_tasks_file_is_planned_and_recorded_with_the_current_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = run_in(tmp_path, monkeypatch, tasks_md(1), tasks_md(1))
    run.record("feature", sizing=OLD_SIZING)
    run.record("other", sizing=OLD_SIZING)
    run.write("feature", tasks_md(2))
    run.runtime.answer = answer(planned("feature/1", (1,)), planned("feature/2", (2,)))

    code, out = tick(run, capsys)

    assert code == 0
    assert run.calls == 1, "only the edited change is asked of the planner"
    assert run.records["feature"]["sizing"] == cli.sizing_digest()
    assert run.records["other"]["sizing"] == OLD_SIZING
    stale = next(line for line in out.splitlines() if "stale" in line)
    assert "other" in stale
    assert "feature" not in stale
