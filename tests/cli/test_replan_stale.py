"""`abk replan` lists a stale plan as stale and records the current digest when it plans one."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.cli.replan_driver import Replan, answer, enable_review, planned, tasks_md
from tests.factories import unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

OLD_SIZING = "a-digest-of-other-ceilings"
PLAN = answer(planned("alpha/1", (1,)))


def listing(run: Replan, capsys: pytest.CaptureFixture[str]) -> dict[str, str]:
    code, out = run.run(capsys)
    assert code == 2
    lines = (line for line in out.splitlines() if ": " in line and "usage" not in line)
    return {line.split(": ", 1)[0]: line for line in lines}


def test_the_listing_marks_a_stale_plan_and_not_a_current_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, alpha=tasks_md(1), beta=tasks_md(1))
    enable_review(run)
    run.record("alpha", sizing=OLD_SIZING)
    run.record("beta", sizing=cli.sizing_digest())

    lines = listing(run, capsys)

    assert "stale" in lines["alpha"]
    assert "stale" not in lines["beta"]
    assert lines["beta"].endswith("planned")


def test_naming_a_stale_change_plans_it_and_records_the_current_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, alpha=tasks_md(1))
    enable_review(run)
    run.record("alpha", sizing=OLD_SIZING)
    assert "stale" in listing(run, capsys)["alpha"]

    code, _ = run.run(capsys, "alpha", reply=PLAN)

    assert code == 0
    assert run.calls == 1
    assert run.records["alpha"]["sizing"] == cli.sizing_digest()
    assert "stale" not in listing(run, capsys)["alpha"]


def test_a_change_with_every_group_taken_gets_the_digest_with_no_planner_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, alpha=tasks_md(1))
    enable_review(run)
    run.store.upsert([unit("alpha/1", change="alpha", groups=(1,))])
    run.store.set_state("alpha/1", IN_REVIEW, pr=5, branch="spec/alpha/1")
    run.record("alpha", sizing=OLD_SIZING)
    assert "stale" in listing(run, capsys)["alpha"]

    code, _ = run.run(capsys, "alpha")

    assert code == 0
    assert run.calls == 0
    assert run.records["alpha"]["sizing"] == cli.sizing_digest()
    assert "stale" not in listing(run, capsys)["alpha"]
