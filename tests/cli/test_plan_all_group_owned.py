"""A plan that gives a started unit's groups to another unit is refused whole and recorded as
failed with its attempts spent (spec: a-started-unit-keeps-its-groups)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import PLANNED
from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.factories import stored_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

COLLIDING = answer(planned("feature/a", (1,)), planned("feature/b", (2,)))
# `feature/1` is taken, so group 1's unit is named `feature/3`; group 2's is `feature/2`.
CLAIMANT = {1: "feature/3", 2: "feature/2"}


def owned_by_a_started_unit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Replan:
    """`feature/1`, planned with a branch, carries both groups; the planner splits them into
    one unit each, so no plan unit has exactly its groups and it is not reused."""
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))
    run.store.upsert([stored_unit("feature/1", change="feature", groups=(1, 2))])
    run.store.set_state("feature/1", PLANNED, branch="spec/feature/1")
    run.runtime.answer = COLLIDING
    return run


def test_the_plan_writes_nothing_and_logs_each_group_with_the_way_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = owned_by_a_started_unit(tmp_path, monkeypatch)
    before = run.store.path.read_bytes()
    capsys.readouterr()

    result = cli.plan_all(run.inst, store=run.store)

    out = capsys.readouterr().out
    assert result["feature"].status == "failed"
    assert run.store.path.read_bytes() == before
    for number in (1, 2):
        lines = [
            line
            for line in out.splitlines()
            if f"group {number}" in line and "feature/1" in line and CLAIMANT[number] in line
        ]
        assert len(lines) == 1, out
        assert "planned" in lines[0]
        assert "abk retire feature/1" in lines[0]
        assert "tasks.md" in lines[0]


def test_the_failure_is_recorded_with_every_attempt_spent_and_the_owners(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = owned_by_a_started_unit(tmp_path, monkeypatch)

    cli.plan_all(run.inst, store=run.store)

    record = run.records["feature"]
    assert record["ok"] is False
    assert record["attempts"] == run.inst.max_plan_attempts
    assert record["owned"] == ["feature/1"]
    assert "feature/1" in record["reason"] and "feature/3" in record["reason"]
    assert "feature/2" in record["reason"]


def test_the_planner_is_not_asked_again_while_tasks_md_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = owned_by_a_started_unit(tmp_path, monkeypatch)
    cli.plan_all(run.inst, store=run.store)
    asked = run.calls
    assert run.records["feature"]["ok"] is False

    cli.plan_all(run.inst, store=run.store)

    assert run.calls == asked


def test_replan_reports_the_refused_plan_as_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = owned_by_a_started_unit(tmp_path, monkeypatch)

    code, out = run.run(capsys, "feature")

    assert code == 1
    assert "the plan failed" in out
    assert run.records["feature"]["owned"] == ["feature/1"]
