"""A refused plan keeps the unit ids the planner returned and why it was refused."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import FAILED
from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.factories import unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

CLAIMS_BUILT = answer(planned("feature/2", (1, 2)))
CLAIMS_ONLY_FREE = answer(planned("feature/2", (2,)))


def fail(run: Replan, uid: str, group: int) -> None:
    run.store.upsert([unit(uid, change="feature", groups=(group,))])
    run.store.set_state(uid, FAILED, branch=f"spec/{uid}")


def refused_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Replan:
    """`feature` group 1 is built by a failed unit; the planner claims it again."""
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))
    fail(run, "feature/1", 1)
    code, _ = run.run(capsys, "feature", reply=CLAIMS_BUILT)
    assert code == 1
    return run


def test_a_planner_that_claims_a_built_group_is_refused_and_no_unit_is_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = refused_run(tmp_path, monkeypatch, capsys)

    assert {u.id for u in run.store.all()} == {"feature/1"}
    assert run.records["feature"]["ok"] is False
    assert run.records["feature"]["units"] == ["feature/2"]


def test_the_record_keeps_the_reason_and_not_the_models_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = refused_run(tmp_path, monkeypatch, capsys)

    reason = run.records["feature"]["reason"]
    assert "group 1" in reason
    assert "Here is the plan" not in reason
    assert "estimated_lines" not in reason


def test_a_bare_replan_shows_the_reason_beside_the_plan_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = refused_run(tmp_path, monkeypatch, capsys)

    code, out = run.run(capsys)

    assert code == 2
    line = next(line for line in out.splitlines() if line.startswith("feature:"))
    assert "failing" in line
    assert run.records["feature"]["reason"] in line


def test_a_later_successful_plan_clears_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = refused_run(tmp_path, monkeypatch, capsys)
    assert run.records["feature"]["reason"]

    code, _ = run.run(capsys, "feature", reply=CLAIMS_ONLY_FREE)

    assert code == 0
    assert run.records["feature"]["ok"] is True
    assert "reason" not in run.records["feature"]
    assert "units" not in run.records["feature"]


def test_a_record_only_plan_clears_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = refused_run(tmp_path, monkeypatch, capsys)
    assert run.records["feature"]["reason"]
    fail(run, "feature/3", 2)
    calls = run.calls

    code, _ = run.run(capsys, "feature")

    assert code == 0
    assert run.calls == calls
    assert run.records["feature"]["ok"] is True
    assert "reason" not in run.records["feature"]


def test_a_reply_with_no_units_keeps_a_reason_naming_the_unclaimed_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))

    code, _ = run.run(capsys, "feature", reply=answer())

    assert code == 1
    record = run.records["feature"]
    assert record["units"] == []
    assert "group(s) 1, 2" in record["reason"]
    _, out = run.run(capsys)
    line = next(line for line in out.splitlines() if line.startswith("feature:"))
    assert record["reason"] in line


def test_a_unit_read_wrongly_keeps_a_reason_and_the_ids_read_so_far(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))
    second = planned("feature/2", (2,)) | {"repo": "nowhere"}

    code, _ = run.run(capsys, "feature", reply=answer(planned("feature/1", (1,)), second))

    assert code == 1
    assert run.records["feature"]["units"] == ["feature/1"]
    assert "nowhere" in run.records["feature"]["reason"]


def test_a_group_too_large_keeps_its_reason_and_the_listing_shows_it_after_given_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1))

    code, _ = run.run(capsys, "feature", reply=answer(planned("feature/1", (1,), lines=100000)))

    assert code == 1
    reason = run.records["feature"]["reason"]
    assert "split" in reason
    _, out = run.run(capsys)
    line = next(line for line in out.splitlines() if line.startswith("feature:"))
    assert f"given up: {reason}" in line
