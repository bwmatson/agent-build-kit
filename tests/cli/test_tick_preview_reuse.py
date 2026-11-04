"""A real tick reuses a valid plan preview a dry-run tick saved (spec: tick-dry-run)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.plan_previews import preview_path
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, read_ledger
from tests.cli.replan_driver import Replan, answer, planned, tasks_md, tick, ticking_replan

pytestmark = pytest.mark.usefixtures("scripted_engine")

REPLY = answer(planned("feature/1", (1,)), planned("feature/2", (2,)))


def previewed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Replan:
    """A planning repo whose `feature` change a dry round has asked the planner about once."""
    run = ticking_replan(tmp_path, monkeypatch, {"feature": tasks_md(2)})
    run.runtime.answer = REPLY
    code, _out = tick(run, capsys, dry_run=True)
    assert code == 0 and run.calls == 1
    assert preview_path(run.inst.state_dir, "feature").is_file()
    return run


def plan_spans(run: Replan) -> int:
    return sum(
        1 for record in read_ledger(run.inst.state_dir / LEDGER_NAME) if record.node == "plan"
    )


def planning_of(run: Replan) -> list[tuple]:
    """What planning wrote for each unit; the rest of a stored unit is what the tick did to it
    after (its state, its times)."""
    return [
        (u.id, u.change, u.repo, u.tier, u.depends_on, u.estimated_lines, u.groups, u.priority)
        for u in run.store.all()
    ]


def test_a_real_tick_plans_from_a_matching_preview_without_asking_and_removes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = previewed(tmp_path, monkeypatch, capsys)
    spans_before = plan_spans(run)

    code, _out = tick(run, capsys)

    assert code == 0
    assert run.calls == 1, "the planner is not asked again"
    assert {u.id for u in run.store.all()} == {"feature/1", "feature/2"}
    assert not preview_path(run.inst.state_dir, "feature").exists()
    assert plan_spans(run) == spans_before, "a reused plan adds no plan span"


def test_a_reused_preview_writes_the_units_a_normal_plan_of_that_answer_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reused = previewed(tmp_path / "reused", monkeypatch, capsys)
    tick(reused, capsys)
    normal = ticking_replan(tmp_path / "normal", monkeypatch, {"feature": tasks_md(2)})
    normal.runtime.answer = REPLY
    tick(normal, capsys)

    assert reused.calls == 1
    assert normal.calls == 1
    assert planning_of(reused) == planning_of(normal)
    assert reused.records == normal.records


@pytest.mark.parametrize("edit", ["tasks", "sizing", "answer"])
def test_a_preview_that_no_longer_fits_is_discarded_and_the_planner_asked_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    edit: str,
) -> None:
    run = previewed(tmp_path, monkeypatch, capsys)
    path = preview_path(run.inst.state_dir, "feature")
    body = json.loads(path.read_text())
    if edit == "tasks":
        run.write("feature", tasks_md(2) + "\nAn added line.\n")
    elif edit == "sizing":
        body["sizing"] = "another-policy"
    else:
        body["answer"] = "I could not make a plan."
    path.write_text(json.dumps(body))

    code, _out = tick(run, capsys)

    assert code == 0
    assert run.calls == 2, "one planner call after the dry run's"
    assert {u.id for u in run.store.all()} == {"feature/1", "feature/2"}
    assert not path.exists(), "the discarded preview is removed"


def test_a_rejected_preview_is_removed_even_when_the_model_call_after_it_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = previewed(tmp_path, monkeypatch, capsys)
    path = preview_path(run.inst.state_dir, "feature")
    path.write_text(json.dumps({**json.loads(path.read_text()), "answer": "No plan."}))
    run.runtime.answer = "Still no plan."

    code, _out = tick(run, capsys)

    assert code == 0
    assert run.calls == 2, "one planner call after the dry run's"
    assert run.records["feature"]["attempts"] == 1, "the failed attempt is recorded"
    assert not path.exists(), "the preview does not outlive the tick that read it"


def test_a_dry_round_asks_again_and_replaces_the_preview_it_finds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = previewed(tmp_path, monkeypatch, capsys)
    second = answer(planned("feature/1", (1,)), planned("feature/2", (2,), lines=90))
    run.runtime.answer = second

    code, _out = tick(run, capsys, dry_run=True)

    assert code == 0
    assert run.calls == 2, "a dry round never reuses a preview"
    saved = json.loads(preview_path(run.inst.state_dir, "feature").read_text())
    assert saved["answer"] == second


def test_a_replan_asks_the_model_whatever_preview_a_dry_round_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = previewed(tmp_path, monkeypatch, capsys)

    code, _out = run.run(capsys, "feature")

    assert code == 0
    assert run.calls == 2, "a replan asks for a fresh answer"


def test_a_preview_for_a_change_that_no_longer_exists_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = previewed(tmp_path, monkeypatch, capsys)
    gone = preview_path(run.inst.state_dir, "removed")
    gone.write_text(json.dumps({"answer": REPLY, "tasks": "x", "sizing": cli.sizing_digest()}))

    code, _out = tick(run, capsys)

    assert code == 0
    assert not gone.exists()
