"""The tick starts and resumes unit threads, and the
poller's events and `abk requeue` resume them, through the entry points a
person or the timer calls (docs/unit-graph.md, Events become resume commands)."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import Node
from agent_build_kit.graph.unit import thread_position
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.events import Review
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW, PLANNED, RUNNING, branch_name
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.workspaces import BranchBusy, branch_lock
from tests.conftest import make_installation
from tests.factories import stored_unit, unit
from tests.graph_driver import fresh
from tests.runner_fakes import Killed, Recorder, make_runner

real_poll_all = cli.poll_all
UNIT = "add-marker/1"
OTHER = "add-marker/2"


class Setup:
    def __init__(
        self,
        inst: Installation,
        recorder: Recorder,
        options: dict[str, Any],
        patch: pytest.MonkeyPatch,
    ) -> None:
        self.inst, self.recorder, self.options, self.patch = inst, recorder, options, patch
        self.store = recorder.store

    def tick(self) -> int:
        return cli.cmd_tick(argparse.Namespace(dry_run=False, only=None), self.inst)

    def next(self, unit_id: str = UNIT) -> tuple[Node, ...]:
        async def look() -> tuple[Node, ...]:
            async with open_checkpointer(unit_graphs_path(self.inst.state_dir)) as saver:
                return (await thread_position(saver, unit_id)).next

        return asyncio.run(look())

    def poll(self, *events: tuple[str, dict[str, Any]], pr: int = 7) -> list[bool]:
        """Report `events` for pull request `pr` as the poller does, and return
        what the dispatch answered each."""
        answers: list[bool] = []

        class Reports:
            def __init__(self, *, repo: str, dispatch: Any, **kwargs: Any) -> None:
                self.repo, self.dispatch = repo, dispatch

            def poll(self) -> None:
                if self.repo != "example/app":
                    return
                for name, kwargs in events:
                    answers.append(self.dispatch(name, pr, pull=None, **kwargs))

        self.patch.setattr(cli, "Poller", Reports)
        real_poll_all(self.inst, store=self.store)
        return answers


@pytest.fixture
def graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Setup:
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        limits={"max_concurrent_stacks": 1},
    )
    recorder = fresh(tmp_path)
    options: dict[str, Any] = {}

    def runner(u: Any, **kwargs: Any) -> Any:
        return make_runner(recorder.store, recorder, tmp_path, **options)

    monkeypatch.setattr(cli, "build_runner", runner)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "verify_ready", lambda inst, units, **kwargs: lambda change: True)
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: [])
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    monkeypatch.setattr(cli, "may_start_unit", lambda r: Decision(may_start=True, reason="plenty"))
    monkeypatch.setattr(
        cli, "build_fetch_review", lambda: lambda repo, pr: Review(lines=["rename the marker"])
    )
    monkeypatch.setattr(cli, "build_restack", lambda **kw: lambda **a: None)
    monkeypatch.setattr(cli, "build_retarget", lambda: lambda unit, base: None)
    return Setup(inst, recorder, options, monkeypatch)


def test_a_tick_builds_a_unit_on_its_thread_and_it_waits_for_review(graph: Setup) -> None:
    assert graph.tick() == 0

    assert graph.store.get(UNIT).state == IN_REVIEW
    assert graph.recorder.pr_opens == 1
    assert graph.next() == (Node.AWAIT_REVIEW,)


def test_a_unit_killed_mid_node_is_resumed_there_by_the_next_tick(graph: Setup) -> None:
    graph.recorder.kill_after = "commit:feat"
    with pytest.raises(Killed):
        graph.tick()
    assert graph.next() == (Node.IMPLEMENT,)
    assert graph.store.get(UNIT).state == RUNNING

    assert graph.tick() == 0

    stored = graph.store.get(UNIT)
    assert stored.state == IN_REVIEW
    assert graph.recorder.made == 2, "one implementation commit"
    assert graph.recorder.events.count("claude:impl") == 1
    states = [entry.get("state") for entry in stored.history]
    assert states == [PLANNED, RUNNING, IN_REVIEW], "never put back to planned"


def test_a_tick_on_which_the_guard_allows_resumes_a_paused_thread(graph: Setup) -> None:
    graph.options["may_start"] = lambda: (False, "session usage at 88%")
    graph.options["resume_at"] = lambda: datetime.now(UTC) + timedelta(hours=1)
    graph.tick()
    assert graph.next() == (Node.TESTS,)
    assert graph.store.get(UNIT).state == RUNNING
    assert (graph.inst.state_dir / "paused.json").exists()

    graph.options.clear()
    graph.tick()

    assert graph.store.get(UNIT).state == IN_REVIEW
    assert graph.next() == (Node.AWAIT_REVIEW,)


def test_a_unit_waiting_in_review_takes_no_slot_and_no_turn_while_another_builds(
    graph: Setup,
) -> None:
    graph.tick()
    assert graph.store.get(UNIT).state == IN_REVIEW
    graph.store.upsert([stored_unit(OTHER)])
    locks = graph.inst.state_dir / "locks"
    held: list[bool] = []

    def worktree_while_the_first_waits(u: Any, base: str) -> Path:
        with (locks / "repo-app.lock").open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                held.append(True)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
                held.append(False)
        try:
            with branch_lock(branch_name(unit()), root=locks):
                held.append(False)
        except BranchBusy:
            held.append(True)
        return graph.inst.state_dir / "tree"

    graph.options["worktree"] = worktree_while_the_first_waits

    graph.tick()  # one stack at a time: the waiting unit holds no slot

    assert graph.store.get(OTHER).state == IN_REVIEW, "built in the one slot there is"
    assert held
    assert not any(held), "no repo turn or branch lock held for the waiting unit"
    assert graph.next() == (Node.AWAIT_REVIEW,)


def test_a_poller_rework_event_positions_the_thread_at_rework_and_the_tick_runs_it(
    graph: Setup,
) -> None:
    graph.tick()
    built = len(graph.recorder.prompts)

    answers = graph.poll(("rework", {"reason": "changes requested"}))

    assert answers == [True]
    assert len(graph.recorder.prompts) == built, "the poll ran no agent"
    assert graph.store.get(UNIT).state == RUNNING
    assert graph.next() == (Node.REWORK,)

    graph.tick()

    assert len(graph.recorder.prompts) == built + 1
    assert "rename the marker" in graph.recorder.prompts[-1]
    assert graph.recorder.events.count("claude:rework") == 1
    assert graph.store.get(UNIT).state == IN_REVIEW
    assert graph.next() == (Node.AWAIT_REVIEW,)


def test_a_poller_event_while_a_run_is_in_a_node_is_kept_and_delivered_after_it(
    graph: Setup,
) -> None:
    graph.tick()
    assert graph.poll(("rework", {"reason": "changes requested"})) == [True]
    answers: list[list[bool]] = []

    def may_start() -> tuple[bool, str]:
        # On the worker thread of the unit's own run, which holds its branch lock.
        if not answers:
            answers.append(graph.poll(("rework", {"reason": "more changes"})))
        return True, "plenty"

    graph.options["may_start"] = may_start

    graph.tick()

    assert answers == [[False]], "deferred, so the poller reports it again"
    assert graph.next() == (Node.AWAIT_REVIEW,)
    assert graph.recorder.events.count("claude:rework") == 1, "the first event's rework only"

    assert graph.poll(("rework", {"reason": "more changes"})) == [True]
    assert graph.next() == (Node.REWORK,)


def test_a_poller_event_for_a_thread_killed_mid_node_is_kept_and_runs_nothing(
    graph: Setup,
) -> None:
    graph.recorder.kill_after = "commit:feat"
    with pytest.raises(Killed):
        graph.tick()
    graph.store.set_state(UNIT, IN_REVIEW, pr=7)
    ran = list(graph.recorder.events)

    answers = graph.poll(("rework", {"reason": "changes requested"}))

    assert answers == [False], "kept: the tick resumes the thread, then it is delivered"
    assert graph.recorder.events == ran
    assert graph.next() == (Node.IMPLEMENT,)


def test_a_poller_event_for_a_unit_whose_node_is_running_is_kept_for_a_later_poll(
    graph: Setup,
) -> None:
    graph.recorder.kill_after = "commit:feat"
    with pytest.raises(Killed):
        graph.tick()
    graph.store.set_state(UNIT, IN_REVIEW, pr=7)
    ran = list(graph.recorder.events)

    with branch_lock(branch_name(unit()), root=graph.inst.state_dir / "locks"):
        answers = graph.poll(("rework", {"reason": "changes requested"}))

    assert answers == [False], "deferred, so the poller reports it again"
    assert graph.recorder.events == ran
    assert graph.next() == (Node.IMPLEMENT,)


def test_a_requeue_of_a_held_unit_leaves_its_thread_at_prepare_and_the_tick_runs_it(
    graph: Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    graph.tick()
    assert graph.poll(("hold", {})) == [True]
    assert graph.store.get(UNIT).state == HELD
    assert graph.next() == (Node.HELD,)
    pushed = len(graph.recorder.remote)
    ran = list(graph.recorder.events)

    args = argparse.Namespace(unit=UNIT, rework=False, restart=False)
    assert cli.cmd_requeue(args, graph.inst) == 0

    assert "thread resumed" in capsys.readouterr().out
    assert graph.recorder.events == ran, "the requeue ran no node"
    assert graph.store.get(UNIT).state == RUNNING
    assert graph.next() == (Node.PREPARE,)

    graph.tick()

    assert graph.store.get(UNIT).state == IN_REVIEW
    assert graph.next() == (Node.AWAIT_REVIEW,)
    assert len(graph.recorder.remote) == pushed, "the work was not redone"


def test_a_comment_on_a_held_unit_waits_and_is_delivered_once_the_tick_has_run_it_back(
    graph: Setup,
) -> None:
    graph.tick()
    assert graph.poll(("hold", {})) == [True]
    comment = ("rework", {"reason": "new comment"})
    assert graph.poll(comment) == [False], "held, so the poller reports it again"

    args = argparse.Namespace(unit=UNIT, rework=False, restart=False)
    assert cli.cmd_requeue(args, graph.inst) == 0
    assert graph.next() == (Node.PREPARE,)
    assert graph.poll(comment) == [False], "the thread has a node to run"

    graph.tick()
    assert graph.next() == (Node.AWAIT_REVIEW,)

    assert graph.poll(comment) == [True]
    assert graph.next() == (Node.REWORK,)
    assert "rename the marker" in graph.store.get(UNIT).feedback


def test_a_merged_parent_tells_its_childs_thread_its_base_moved(graph: Setup) -> None:
    restacked: list[dict[str, Any]] = []
    retargeted: list[tuple[str, str]] = []
    graph.patch.setattr(cli, "build_restack", lambda **kw: lambda **a: restacked.append(a))
    graph.patch.setattr(
        cli, "build_retarget", lambda: lambda u, base: retargeted.append((u.id, base))
    )
    graph.tick()
    graph.store.upsert([stored_unit(OTHER, depends_on=(UNIT,))])
    graph.tick()
    assert graph.store.get(OTHER).state == IN_REVIEW
    assert graph.next(OTHER) == (Node.AWAIT_REVIEW,)
    built = len(graph.recorder.prompts)

    assert graph.poll(("merged", {})) == [True]

    assert graph.store.get(UNIT).state == "merged"
    assert graph.next(OTHER) == (Node.PREPARE,)
    assert graph.store.get(OTHER).state == RUNNING
    assert restacked == [], "the classic restack did not move it"
    assert retargeted == [(OTHER, "main")], "its PR left the merged branch at once"
    assert len(graph.recorder.prompts) == built

    graph.tick()

    assert graph.next(OTHER) == (Node.AWAIT_REVIEW,)


def test_a_merged_parent_leaves_a_held_childs_thread_and_state_alone(graph: Setup) -> None:
    graph.tick()
    graph.store.upsert([stored_unit(OTHER, depends_on=(UNIT,))])
    graph.tick()
    graph.store.set_state(OTHER, IN_REVIEW, pr=8)
    assert graph.poll(("hold", {}), pr=8) == [True]
    assert graph.store.get(OTHER).state == HELD
    assert graph.next(OTHER) == (Node.HELD,)
    ran = list(graph.recorder.events)

    assert graph.poll(("merged", {})) == [True]

    assert graph.store.get(OTHER).state == HELD
    assert graph.next(OTHER) == (Node.HELD,)

    graph.tick()

    assert graph.recorder.events == ran, "a unit a person held was not run again"
    assert graph.store.get(OTHER).state == HELD


def _ended_failed_after_review(graph: Setup) -> None:
    """A unit in review whose rework run ends in `failed`, its PR still open."""
    graph.tick()
    graph.recorder.tier1_ok = False
    assert graph.poll(("rework", {"reason": "changes requested"})) == [True]
    graph.tick()
    assert graph.store.get(UNIT).state == FAILED
    assert graph.next() == ()
    graph.recorder.tier1_ok = True


def test_a_hold_for_a_unit_whose_thread_ended_failed_holds_it(graph: Setup) -> None:
    _ended_failed_after_review(graph)

    assert graph.poll(("hold", {})) == [True]

    assert graph.store.get(UNIT).state == HELD


def test_a_rework_for_a_unit_whose_thread_ended_failed_plans_it_with_the_feedback(
    graph: Setup,
) -> None:
    _ended_failed_after_review(graph)

    assert graph.poll(("rework", {"reason": "changes requested"})) == [True]

    stored = graph.store.get(UNIT)
    assert stored.state == PLANNED
    assert stored.feedback


def _raised_in_a_node(graph: Setup) -> None:
    """A unit whose first node raises a plain error, so the tick records it failed."""

    def boom(*args: Any, **kwargs: Any) -> int:
        raise RuntimeError("git exploded")

    graph.options["commit"] = boom
    assert graph.tick() == 0
    del graph.options["commit"]
    assert graph.store.get(UNIT).state == FAILED
    assert graph.next(), "the thread still shows the node that raised"


def test_a_unit_whose_node_raised_can_be_requeued_and_the_tick_runs_it_from_prepare(
    graph: Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    _raised_in_a_node(graph)

    args = argparse.Namespace(unit=UNIT, rework=False, restart=False)
    assert cli.cmd_requeue(args, graph.inst) == 0

    assert "thread resumed" in capsys.readouterr().out
    assert graph.store.get(UNIT).state == RUNNING
    assert graph.next() == (Node.PREPARE,)

    graph.tick()

    assert graph.store.get(UNIT).state == IN_REVIEW
    assert graph.next() == (Node.AWAIT_REVIEW,)


def test_a_rework_for_a_unit_whose_node_raised_is_handled_not_deferred(graph: Setup) -> None:
    _raised_in_a_node(graph)
    graph.store.set_state(UNIT, FAILED, pr=7)

    assert graph.poll(("rework", {"reason": "changes requested"})) == [True]

    stored = graph.store.get(UNIT)
    assert stored.state == PLANNED
    assert stored.feedback

    graph.tick()

    assert graph.store.get(UNIT).state == IN_REVIEW


def test_a_hold_for_a_unit_whose_node_raised_holds_it(graph: Setup) -> None:
    _raised_in_a_node(graph)
    graph.store.set_state(UNIT, FAILED, pr=7)

    assert graph.poll(("hold", {})) == [True]

    assert graph.store.get(UNIT).state == HELD


def test_a_run_holds_the_branch_lock_between_its_nodes(graph: Setup) -> None:
    locks = graph.inst.state_dir / "locks"
    held: list[bool] = []

    def may_start() -> tuple[bool, str]:
        held.append(cli.branch_is_held(graph.inst, branch_name(unit())))
        return True, "plenty"

    graph.options["may_start"] = may_start

    graph.tick()

    assert held
    assert all(held), "held before every agent node, between nodes"
    assert graph.store.get(UNIT).state == IN_REVIEW
    assert not list(locks.glob("*.lock")), "released once the thread waits"


def test_a_build_for_a_unit_another_run_is_between_nodes_on_is_skipped(graph: Setup) -> None:
    graph.store.set_state(UNIT, RUNNING)
    ran = list(graph.recorder.events)

    with branch_lock(branch_name(unit()), root=graph.inst.state_dir / "locks"):
        graph.tick()

    assert graph.recorder.events == ran, "no node ran"
    # The only thing the tick did is move the unit onto a thread, still before its first node.
    assert graph.next() == (Node.PREPARE,)
