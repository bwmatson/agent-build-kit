"""A dry-run tick plans in memory and writes only the plan previews (spec: tick-dry-run)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import network_probe
from agent_build_kit.pipeline.pause import PAUSE_MARKER, network_marker, pause_until
from agent_build_kit.pipeline.unit_store import ClosePending
from agent_build_kit.pipeline.units import IN_REVIEW, RUNNING, SATISFIED
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.runtimes import AgentRequest
from tests.branch_lock_fakes import dead_pid, lock_held_by
from tests.cli.replan_driver import Replan, answer, planned, tasks_md, tick, ticking_replan
from tests.factories import unit
from tests.split_step_support import correct, scene
from tests.split_step_support import reply as split_reply
from tests.tick_pass import isolate

pytestmark = pytest.mark.usefixtures("scripted_engine")

PREVIEWS = "plan-previews"
THREAD_STORE = "unit-graphs.sqlite"
GROUPS = {"feature": 2, "other": 1}


def reply_for(change: str) -> str:
    """What the planner answers for `change`: one unit per group of its tasks file."""
    return answer(*(planned(f"{change}/{n}", (n,)) for n in range(1, GROUPS[change] + 1)))


def answering_per_change(run: Replan) -> None:
    def reply(request: AgentRequest) -> None:
        run.runtime.answer = reply_for(request.change)

    run.runtime.act = reply


def preview_file(run: Replan, change: str) -> Path:
    return run.inst.state_dir / PREVIEWS / f"{change}.json"


def state_bytes(run: Replan) -> dict[str, str]:
    """Every file under the state folder as a digest of its bytes, but for the previews, the
    empty `.lock` handles and thread database a read opens, and the usage ledger, which every
    tick appends its spans and metrics to (and records the planner call a dry run makes in, as
    any spend is)."""
    root = run.inst.state_dir
    return {
        str(path.relative_to(root)): hashlib.sha1(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.suffix != ".lock"
        and path.name not in (LEDGER_NAME, THREAD_STORE)
        and PREVIEWS not in path.relative_to(root).parts
    }


def test_a_dry_round_asks_for_each_changed_change_and_writes_only_the_previews(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = ticking_replan(tmp_path, monkeypatch, {"feature": tasks_md(2), "other": tasks_md(1)})
    answering_per_change(run)
    before = state_bytes(run)

    code, out = tick(run, capsys, dry_run=True)

    assert code == 0
    assert run.calls == 2, "the planner is asked once for each changed change"
    assert "would plan feature: 2 unit(s)" in out
    assert "would plan other: 1 unit(s)" in out
    assert state_bytes(run) == before, "units.json, planned.json and the rest are untouched"
    for change in GROUPS:
        saved = json.loads(preview_file(run, change).read_text()).values()
        assert reply_for(change) in saved, "the planner's raw answer"
        assert cli.plan_digest(run.inst.changes_dir / change / "tasks.md") in saved
        assert cli.sizing_digest() in saved


def test_a_dry_round_with_nothing_to_plan_writes_nothing_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = ticking_replan(tmp_path, monkeypatch, {"feature": tasks_md(2)})
    answering_per_change(run)
    tick(run, capsys, dry_run=True)
    assert preview_file(run, "feature").is_file(), "the stale plan is saved as a preview"
    # The change now stands planned and its preview is gone: nothing is left to plan.
    preview_file(run, "feature").unlink()
    preview_file(run, "feature").parent.rmdir()
    run.record("feature", sizing=cli.sizing_digest())
    # Something else in progress makes the tick run, so planning is looked at.
    run.store.upsert([unit("other/1", change="other", groups=(1,))])
    run.store.set_state("other/1", IN_REVIEW, pr=5, branch="spec/other/1")
    before = state_bytes(run)
    calls = run.calls

    code, out = tick(run, capsys, dry_run=True)

    assert code == 0
    assert run.calls == calls
    assert "would plan" not in out
    assert not (run.inst.state_dir / PREVIEWS).exists(), "no preview folder either"
    assert state_bytes(run) == before


def test_a_dry_round_under_a_usage_refusal_makes_no_planner_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = ticking_replan(tmp_path, monkeypatch, {"feature": tasks_md(2)})
    answering_per_change(run)
    tick(run, capsys, dry_run=True)
    assert run.calls == 1 and preview_file(run, "feature").is_file()
    preview_file(run, "feature").unlink()
    run.write("other", tasks_md(1))
    run.runtime.supports_usage_tracking = True
    monkeypatch.setattr(
        cli, "may_start_unit", lambda r, **_: Decision(may_start=False, reason="window used up")
    )
    before = state_bytes(run)

    code, out = tick(run, capsys, dry_run=True)

    assert code == 0
    assert run.calls == 1, "a refused round plans nothing"
    assert "would plan" not in out
    assert not list(preview_file(run, "other").parent.glob("*.json"))
    assert state_bytes(run) == before, "the refusal writes no pause marker"
    assert not (run.inst.state_dir / PAUSE_MARKER).exists()


def test_a_dry_round_leaves_a_standing_pause_when_the_guard_allows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = ticking_replan(tmp_path, monkeypatch, {"feature": tasks_md(2)})
    answering_per_change(run)
    run.runtime.supports_usage_tracking = True
    marker = run.inst.state_dir / PAUSE_MARKER
    pause_until(None, reason="session at 99%", marker=marker)
    before = state_bytes(run)

    code, _out = tick(run, capsys, dry_run=True)

    assert code == 0
    assert marker.is_file(), "a command run only to look does not end a pause"
    assert state_bytes(run) == before


def test_a_dry_round_does_not_fail_a_running_unit_whose_run_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = ticking_replan(tmp_path, monkeypatch, {"feature": tasks_md(1)})
    run.record("feature", sizing=cli.sizing_digest())
    run.store.upsert([unit("other/1", change="other", groups=(1,))])
    run.store.set_state("other/1", RUNNING, branch="spec/other/1")
    lock_held_by(run.inst, "spec/other/1", dead_pid())
    before = state_bytes(run)

    code, _out = tick(run, capsys, dry_run=True)

    assert code == 0
    assert run.store.get("other/1").state == RUNNING
    assert state_bytes(run) == before


def test_a_dry_round_leaves_a_network_pause_and_the_plans_waiting_on_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = ticking_replan(tmp_path, monkeypatch, {"feature": tasks_md(1)})
    later = datetime.now(UTC) + timedelta(hours=1)
    run.record(
        "feature",
        sizing=cli.sizing_digest(),
        ok=False,
        waiting="network",
        until=later.isoformat(),
    )
    marker = network_marker(run.inst.state_dir)
    pause_until(later, reason="network unreachable", marker=marker, kind="network")
    monkeypatch.setattr(network_probe, "control_reachable", lambda inst: True)
    run.store.upsert([unit("other/1", change="other", groups=(1,))])
    run.store.set_state("other/1", IN_REVIEW, pr=5, branch="spec/other/1")
    before = state_bytes(run)

    code, _out = tick(run, capsys, dry_run=True)

    assert code == 0
    assert marker.is_file(), "the network pause is not ended by a command run only to look"
    assert state_bytes(run) == before, "planned.json still says what it waits for"


def test_a_dry_round_closes_no_pull_request_and_clears_no_pending_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = ticking_replan(tmp_path, monkeypatch, {"feature": tasks_md(1)})
    run.record("feature", sizing=cli.sizing_digest())
    run.store.upsert([unit("other/1", change="other", groups=(1,))])
    run.store.set_state("other/1", SATISFIED, pr=4)
    run.store.set_close_pending("other/1", ClosePending(pr=4, reason="Elsewhere."))
    closed: list[int] = []
    monkeypatch.setattr(
        cli, "build_close_pr", lambda **_: lambda unit, pr, reason: closed.append(pr)
    )
    before = state_bytes(run)

    code, _out = tick(run, capsys, dry_run=True)

    assert code == 0
    assert closed == []
    assert run.store.get("other/1").close_pending is not None
    assert state_bytes(run) == before


def test_a_dry_round_over_a_populated_store_changes_no_stored_state_and_splits_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # `feature/1` is held for its size with a split to make and `feature/6` waits on it;
    # `other` is edited to need `feature` group 1, so a real round would link `other/1` to it.
    run = scene(tmp_path, monkeypatch)
    run.record("feature")
    run.write("other", tasks_md(1, needs={1: "feature group 1 merged"}))
    run.store.upsert([unit("other/1", change="other", groups=(1,))])
    plan_all = cli.plan_all
    isolate(monkeypatch)
    monkeypatch.setattr(cli, "plan_all", plan_all)
    requests: list[str] = []

    def reply_to(request: AgentRequest) -> None:
        requests.append(request.change)
        run.runtime.answer = (
            answer(planned("other/1", (1,)))
            if request.change == "other"
            else split_reply(*correct())
        )

    run.runtime.act = reply_to
    before = state_bytes(run)
    stored = run.store.all()

    code, out = tick(run, capsys, dry_run=True)

    assert code == 0
    assert requests == ["other"], "one planner call for the changed change and no split call"
    assert "would plan other: 1 unit(s)" in out
    assert state_bytes(run) == before, "units.json, planned.json, markers and logs untouched"
    assert run.store.all() == stored
