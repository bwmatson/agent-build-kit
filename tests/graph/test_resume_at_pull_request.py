"""A unit whose approved commit is its pushed head, resumed after a failure of the
pull request step, goes straight to that step: tier 2 does not run again, nothing is
reviewed, and saved feedback is not reworked. A unit whose head moved still takes the
checks path."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import UnitRun
from agent_build_kit.graph.unit import run_unit, seed_thread
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import FAILED, IN_REVIEW, PLANNED
from tests.conftest import make_installation
from tests.factories import unit
from tests.graph.test_build_path import build
from tests.runner_fakes import Recorder, make_runner

HEAD = "sha-1"
UNIT = unit().id


def pushed(tmp_path: Path, *, tier: str = "tier1", approved: str = HEAD) -> Recorder:
    """A unit whose pull request step failed after its work was approved and
    pushed: one commit on the branch, with `approved` and the remote at `HEAD`."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(tier=tier)])
    recorder = Recorder(store)
    recorder.made = 1
    recorder.remote.append(HEAD)
    store.record_push(UNIT, HEAD)
    store.record_approval(UNIT, approved)
    return recorder


def test_a_tier_two_unit_does_not_run_tier_two_again(tmp_path: Path) -> None:
    recorder = pushed(tmp_path, tier="tier2")

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    assert recorder.pr_opens == 1
    assert "tier2" not in recorder.events
    assert "review" not in recorder.events


def test_a_unit_with_saved_feedback_does_not_go_back_to_rework(tmp_path: Path) -> None:
    recorder = pushed(tmp_path)
    recorder.store.set_feedback(UNIT, "Rename the helper.")

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    assert "claude:rework" not in recorder.events
    assert "review" not in recorder.events
    assert recorder.pr_opens == 1
    assert recorder.store.get(UNIT).feedback == "", "cleared by the pull request step, as now"
    assert recorder.store.get(UNIT).state == IN_REVIEW


def test_a_unit_whose_head_moved_still_takes_the_checks_path(tmp_path: Path) -> None:
    recorder = pushed(tmp_path, approved="sha-0")

    build(tmp_path, recorder)

    assert recorder.events.index("tier1") < recorder.events.index("review")


def test_a_unit_with_a_pull_request_and_replies_still_owed_goes_to_the_pull_request_step(
    tmp_path: Path,
) -> None:
    recorder = pushed(tmp_path)
    recorder.store.set_state(UNIT, PLANNED, pr=5)
    recorder.prs[f"spec/{UNIT}"] = 5
    replies: list[str] = []

    async def seed_and_run() -> None:
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            owed = UnitRun(
                unit_id=UNIT, change="add-marker", groups=(1,), pending_replies=("Done.",)
            )
            await seed_thread(saver, owed)
            runner = make_runner(
                recorder.store,
                recorder,
                tmp_path,
                reply=lambda **kw: replies.append(kw["answer_text"]),
            )
            await run_unit(runner, recorder.store.get(UNIT), base="main", graph=[], saver=saver)

    asyncio.run(seed_and_run())

    assert replies == ["Done."]
    assert "claude:rework" not in recorder.events
    assert "review" not in recorder.events
    assert "push" not in recorder.events, "straight to the pull request step"
    assert recorder.store.get(UNIT).state == IN_REVIEW


def test_a_stop_in_the_graph_fails_the_unit_with_its_reason_and_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder(store, tier1_ok=False)
    recorder.tier1_output = "E   ImportError: cannot import name 'geo'"

    build(tmp_path, recorder)

    stored = store.get(UNIT)
    assert stored.state == FAILED
    assert "checks still failing" in stored.note
    assert stored.step == "checks"
    inst = make_installation(tmp_path, planning={"state_dir": "."})
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    assert cli.cmd_status(argparse.Namespace(), inst) == 0
    line = next(x for x in capsys.readouterr().out.splitlines() if "failed:" in x)
    assert UNIT in line and "at checks" in line and "checks still failing" in line
