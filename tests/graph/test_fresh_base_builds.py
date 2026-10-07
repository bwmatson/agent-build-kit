"""A unit checks its base against the remote at the start of a run and again
before it pushes, on the graph engine.

The move itself is `restack_onto`, whose behaviour with real git is covered
where it lives; what is asserted here is when the engine asks for it and what
it does with the answer.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.stack_runner import PauseInfo, Restacked, RunStatus
from agent_build_kit.pipeline.units import IN_REVIEW
from agent_build_kit.pipeline.wiring import Tier2Session
from tests.factories import unit
from tests.graph.test_build_path import build, restacked
from tests.graph.test_remaining_paths import fresh
from tests.graph_driver import position
from tests.runner_fakes import Recorder

MOVED = "moved-sha"
CLEAN = restacked()
RESOLVED = restacked(resolved=("a.py",))


class Moving:
    """A restack that finds the branch on its base until review has run, then
    answers from `results`; a move that is not resolved puts the branch at
    `MOVED`, carrying the approval only if `carries_approval`."""

    def __init__(
        self, recorder: Recorder, *results: Restacked | None, carries_approval: bool = True
    ) -> None:
        self.recorder = recorder
        self.results = list(results)
        self.carries_approval = carries_approval
        self.moved = False

    def head(self, cwd: Path) -> str:
        return MOVED if self.moved else self.recorder.head(cwd)

    def restack(self, **kw: Any) -> Restacked | None:
        if "review" not in self.recorder.events or not self.results:
            return None
        result = self.results.pop(0)
        if result is not None:
            self.moved = True
            self.recorder.events.append("moved")
            if self.carries_approval and not result.resolved:
                self.recorder.store.record_approval("add-marker/1", MOVED)
        return result

    def overrides(self) -> dict[str, Any]:
        return {"head": self.head, "restack_onto": self.restack}


def test_a_run_with_commits_on_its_branch_fetches_before_it_restacks(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.made = 2

    build(
        tmp_path,
        recorder,
        fetch=lambda u: recorder.events.append("fetch"),
        restack_onto=lambda **kw: recorder.events.append("restack"),
    )

    assert recorder.events[:2] == ["fetch", "restack"]


def test_a_fetch_that_fails_is_logged_and_does_not_fail_the_unit(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.made = 2

    def unreachable(u: Any) -> None:
        raise RuntimeError("could not resolve host: origin")

    outcome = build(
        tmp_path,
        recorder,
        fetch=unreachable,
        restack_onto=lambda **kw: recorder.events.append("restack"),
    )

    assert outcome.status == "open"
    assert any("could not resolve host" in line for line in recorder.logged)
    assert "restack" in recorder.events, "the run goes on with the refs it has"


def test_a_forge_that_cannot_be_asked_leaves_the_unit_on_its_base_and_is_logged(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    opened: list[str] = []

    def unreachable(u: Any, base: str) -> str:
        raise RuntimeError("gh: HTTP 502 from api.example.test")

    def open_pr(u: Any, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
        opened.append(base)
        return recorder.open_pr(u, body=body, base=base, cwd=cwd)

    outcome = build(
        tmp_path, recorder, base="spec/add-marker/0", fresh_base=unreachable, open_pr=open_pr
    )

    assert outcome.status == "open"
    assert opened == ["spec/add-marker/0"], "opened on the base the run had"
    assert any("HTTP 502" in line for line in recorder.logged)


def test_a_clean_move_before_the_push_is_checked_again_without_another_review_or_agent(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    moving = Moving(recorder, CLEAN)

    outcome = build(tmp_path, recorder, **moving.overrides())

    assert outcome.status == "open"
    assert recorder.events.count("tier1") == 2
    assert recorder.events.count("review") == 1, "no review round is spent on a clean move"
    assert len(recorder.prompts) == 2, "no agent is called for it"
    assert recorder.events.index("moved") < recorder.events.index("push")
    assert recorder.store.get("add-marker/1").approved == MOVED


def test_a_move_with_resolution_is_checked_and_reviewed_again_before_anything_is_pushed(
    tmp_path: Path,
) -> None:
    """The resolution rewrote the branch, so the commit review approved is not
    the commit that would be pushed: checked first, as before every review, so
    a resolution that broke the build never reaches a reviewer."""
    recorder = fresh(tmp_path)
    moving = Moving(recorder, RESOLVED)

    pushed: list[str] = []

    def push(branch: str, *, cwd: Path) -> str:
        pushed.append(moving.head(cwd))
        return recorder.push(branch, cwd=cwd)

    outcome = build(tmp_path, recorder, push=push, **moving.overrides())

    assert outcome.status == "open"
    assert recorder.events.count("review") == 2, "read again, not passed on the old approval"
    assert pushed == [MOVED], "only the commit the second review approved was pushed"
    after = recorder.events[recorder.events.index("moved") :]
    assert after.index("tier1") < after.index("review") < after.index("push")
    assert recorder.store.get("add-marker/1").approved == MOVED


def test_tier_one_failing_after_a_clean_move_waits_for_the_usage_window_before_its_rework(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    moving = Moving(recorder, CLEAN)
    recorder.tier1_results = [(True, ""), (False, "FAILED test_a - trunk renamed the helper")]

    def window() -> tuple[bool, str]:
        failed = "trunk renamed the helper" in recorder.store.get("add-marker/1").feedback
        return (not failed, "session at 88%" if failed else "usage fine")

    outcome = build(tmp_path, recorder, may_start=window, **moving.overrides())

    assert outcome.status == RunStatus.PAUSED, "the resumed run is gated on usage like any other"
    assert "push" not in recorder.events and "pr" not in recorder.events
    paused = position(tmp_path)
    assert paused.pause == PauseInfo(reason="session at 88%")
    assert paused.next == (Node.REWORK,)
    assert "trunk renamed the helper" in recorder.store.get("add-marker/1").feedback


def test_tier_two_failing_after_a_clean_move_waits_with_its_output(tmp_path: Path) -> None:
    recorder = fresh(tmp_path, tier="tier2")
    moving = Moving(recorder, CLEAN)
    answers = iter([(True, "## before"), (False, "FAILED live_test - trunk renamed the route")])
    recorder.tier2 = lambda *, cwd: next(answers)  # type: ignore[method-assign]

    def window() -> tuple[bool, str]:
        failed = "trunk renamed the route" in recorder.store.get("add-marker/1").feedback
        return (not failed, "session at 88%" if failed else "usage fine")

    outcome = build(
        tmp_path,
        recorder,
        run_tier2=recorder.tier2,
        may_start=window,
        **moving.overrides(),
    )

    assert outcome.status == RunStatus.PAUSED
    assert "push" not in recorder.events and "pr" not in recorder.events
    assert "trunk renamed the route" in recorder.store.get("add-marker/1").feedback


def test_a_tier_two_unit_moved_cleanly_posts_its_status_for_the_moved_commit(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, tier="tier2")
    moving = Moving(recorder, CLEAN)
    (tmp_path / "tree" / "scripts").mkdir(parents=True)
    (tmp_path / "tree" / "scripts" / "dev-stack.sh").write_text("#!/bin/sh\n")
    statuses: list[str] = []
    ran: list[str] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        ran.append(command[-1])
        return subprocess.CompletedProcess(command, 0, "5 passed in 1.00s", "")

    # The real session: it refuses a status for a commit it did not run against.
    session = Tier2Session(
        unit(tier="tier2"),
        lock=tmp_path / "t2.lock",
        run=run,
        sha=moving.head,
        status=lambda repo, result: statuses.append(result.sha),
    )

    outcome = build(
        tmp_path,
        recorder,
        run_tier2=session.run,
        post_status=session.post,
        push=lambda branch, *, cwd: moving.head(cwd),
        **moving.overrides(),
    )

    assert outcome.status == "open"
    assert recorder.store.get("add-marker/1").state == IN_REVIEW
    assert ran.count("test") == 2, "tier 2 ran before the move and again after it"
    assert statuses == [MOVED], "the status is for the commit that was pushed and re-tested"
