"""A unit checks its base against the remote, at the start of a run and again
before it pushes.

Driven through the runner with the usual doubles: the move itself is `restack_onto`,
whose behaviour with real git is covered where it lives; what is asserted here is
when the runner asks for it and what it does with the answer.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.forges.base import BaseMissing
from agent_build_kit.pipeline.stack_runner import RESTACK, Restacked, UnitRunner
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, local_ref
from agent_build_kit.pipeline.wiring import Tier2Session
from tests.factories import unit
from tests.pipeline.test_stack_runner import Recorder, make_runner

MOVED = "moved-sha"
CLEAN = Restacked(onto_unit="main", onto_intent="the trunk", old_base="a", old_head="sha-2")
RESOLVED = Restacked(
    onto_unit="main", onto_intent="the trunk", old_base="a", old_head="sha-2", resolved=("a.py",)
)
CONFLICTED = Restacked(
    onto_unit="main", onto_intent="the trunk", old_base="a", old_head="sha-2", conflict="a.py"
)


class Harness:
    """A runner whose fetch, base and move are recorded in the recorder's order."""

    def __init__(self, tmp_path: Path, *, existing: int = 0, tier: str = "tier1") -> None:
        self.unit = unit(tier=tier)
        self.store = UnitStore(tmp_path / "units.json")
        self.store.upsert([self.unit])
        self.recorder = Recorder()
        self.events = self.recorder.events
        self.moved = False
        self.restack_bases: list[str] = []
        self.resolving: list[bool] = []
        self.opened_on: list[str] = []
        self.fetch_error: Exception | None = None
        self.base_now = "main"
        self.move_result: Restacked | Exception | None = None
        # What each move gives after the first, in order; None once spent.
        self.later: list[Restacked | Exception | None] = []
        self.runner: UnitRunner = make_runner(self.store, self.recorder, tmp_path)
        self.runner.fetch = self.fetch
        self.runner.fresh_base = self.fresh_base
        self.runner.head = self.head
        self.runner.open_pr = self.open_pr
        self.runner.restack_onto = self.restack_onto
        if existing:
            self.runner.branch_commits = lambda cwd, base: existing + self.recorder.made

    def fetch(self, unit) -> None:
        self.events.append("fetch")
        if self.fetch_error:
            raise self.fetch_error

    def fresh_base(self, unit, base: str) -> str:
        self.events.append("fresh_base")
        return self.base_now

    def head(self, cwd: Path) -> str:
        return MOVED if self.moved else self.recorder.head(cwd)

    def open_pr(self, unit, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
        self.opened_on.append(base)
        return self.recorder.open_pr(unit, body=body, base=base, cwd=cwd, **bodies)

    def restack_onto(
        self, *, tree: Path, branch: str, base: str, unit, resolve: bool = True
    ) -> Restacked | None:
        self.events.append("restack")
        self.restack_bases.append(base)
        self.resolving.append(resolve)
        # The start of a run that resumes: the branch is already on its base.
        if "review" not in self.events:
            return None
        result, self.move_result = self.move_result, (self.later.pop(0) if self.later else None)
        if isinstance(result, Exception):
            raise result
        if result is not None and not result.resolved and not result.conflict:
            # What the real move does for a clean replay of an approved commit.
            self.moved = True
            self.store.record_approval(unit.id, MOVED)
        return result

    def close_window_after_one_run(self) -> None:
        """The usage gate is open until the unit is held for its base, then shut."""

        def may_start() -> tuple[bool, str]:
            held = "base moved before its push" in self.store.get(self.unit.id).note
            return (not held, "session at 88%" if held else "usage fine")

        self.runner.may_start = may_start

    def run(self, *, base: str = "main"):
        return self.runner.run(self.unit, base=base, graph=[])


def test_a_run_with_commits_on_its_branch_fetches_before_it_restacks(tmp_path: Path) -> None:
    harness = Harness(tmp_path, existing=2)

    harness.run()

    assert harness.events[:2] == ["fetch", "restack"]


def test_a_fetch_that_fails_is_logged_and_does_not_fail_the_unit(tmp_path: Path) -> None:
    harness = Harness(tmp_path, existing=2)
    harness.fetch_error = RuntimeError("could not resolve host: origin")

    outcome = harness.run()

    assert outcome.status == "open"
    assert any("could not resolve host" in line for line in harness.recorder.logged)
    assert "restack" in harness.events, "the run goes on with the refs it has"


def test_a_clean_move_before_the_push_reruns_tier_one_then_pushes(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    harness.move_result = CLEAN

    outcome = harness.run()

    assert outcome.status == "open"
    assert harness.events[-6:] == ["fetch", "fresh_base", "restack", "tier1", "push", "pr"]
    assert harness.events.count("tier1") == 2
    assert harness.events.count("review") == 1, "no review round is spent on a clean move"
    assert len(harness.recorder.prompts) == 2, "no agent is called for it"
    assert not harness.store.get(unit().id).review_rounds


def test_a_branch_already_on_its_base_is_pushed_without_a_second_tier_one(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    harness.move_result = None

    harness.run()

    assert harness.events.count("tier1") == 1
    assert harness.events[-5:] == ["fetch", "fresh_base", "restack", "push", "pr"]


@pytest.mark.parametrize(
    "result",
    [RESOLVED, CONFLICTED, RuntimeError("both sides changed a.py")],
    ids=["resolved", "conflicted", "unresolvable"],
)
def test_a_move_that_needs_resolution_before_the_push_resumes_at_its_restack_at_once(
    tmp_path: Path, result: Restacked | Exception
) -> None:
    harness = Harness(tmp_path, existing=2)
    harness.move_result = result

    outcome = harness.run()

    assert outcome.status == "open", "the same run goes on, rather than queueing"
    assert harness.resolving == [True, False, True, False], "the resumed restack may resolve"
    assert harness.events.count("push") == 1, "nothing is pushed from the half-resolved branch"
    assert any("base moved before its push" in line for line in harness.recorder.logged)


def test_a_base_that_keeps_needing_resolution_is_resumed_once_then_left_planned(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path, existing=2)
    # The push-time move, the resumed run's own restack, its push-time move.
    harness.move_result = RESOLVED
    harness.later = [None, RESOLVED]

    outcome = harness.run()

    stored = harness.store.get(unit().id)
    assert outcome.status == "held"
    assert "push" not in harness.events and "pr" not in harness.events
    assert stored.state == PLANNED
    assert stored.resume_from == RESTACK
    assert "base moved before its push" in stored.note
    assert harness.resolving.count(False) == 2, "one resume, not a loop"


def test_a_parent_merged_unknown_to_the_store_moves_the_unit_onto_the_trunk(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path)
    harness.move_result = CLEAN
    harness.base_now = "main"

    outcome = harness.run(base="spec/add-marker/0")

    assert outcome.status == "open"
    assert harness.restack_bases[-1] == local_ref("main")
    assert harness.opened_on == ["main"], "the pull request opens on the new base"


def test_tier_one_failing_after_a_clean_move_holds_the_unit_for_rework(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    harness.move_result = CLEAN
    answers = iter([(True, ""), (False, "FAILED test_a - trunk renamed the helper")])

    def tier1(*, cwd: Path, base: str = "main", whole_repo: bool = False) -> tuple[bool, str]:
        harness.events.append("tier1")
        return next(answers)

    harness.runner.run_tier1 = tier1
    harness.close_window_after_one_run()

    outcome = harness.run()

    stored = harness.store.get(unit().id)
    assert outcome.status == "paused", "the resumed run is gated on usage like any other"
    assert "push" not in harness.events
    assert stored.state == PLANNED
    assert "trunk renamed the helper" in stored.feedback


def test_an_approved_branch_moved_cleanly_is_pushed_at_the_moved_commit(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    harness.move_result = CLEAN

    harness.run()

    assert harness.store.get(unit().id).approved == MOVED
    assert harness.events.count("review") == 1
    assert "push" in harness.events


def test_a_branch_moved_with_resolution_is_not_passed_on_the_old_approval(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path)
    harness.move_result = RESOLVED
    harness.close_window_after_one_run()

    harness.run()

    approved = harness.store.get(unit().id).approved
    assert approved and approved != MOVED, "still the commit the review read"
    assert "push" not in harness.events


def test_a_base_gone_at_open_is_asked_for_again_and_the_unit_goes_on_from_the_new_one(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path, existing=2)
    harness.base_now = "spec/add-marker/0"
    opened: list[str] = []

    def gone(unit, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
        opened.append(base)
        if base == "spec/add-marker/0":
            # Merged, and its branch deleted, after the check above said otherwise.
            harness.base_now = "main"
            raise BaseMissing("base branch spec/add-marker/0 does not exist")
        return harness.recorder.open_pr(unit, body=body, base=base, cwd=cwd, **bodies)

    harness.runner.open_pr = gone

    outcome = harness.run(base="spec/add-marker/0")

    assert outcome.status == "open"
    assert opened == ["spec/add-marker/0", "main"], "the retry is on the merged-to base"
    assert harness.store.get(unit().id).state == IN_REVIEW


def test_a_base_gone_at_open_that_the_forge_still_names_holds_the_unit_and_other_refusals_fail(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path, existing=2)
    harness.base_now = "spec/add-marker/0"

    def gone(unit, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
        raise BaseMissing("base branch spec/add-marker/0 does not exist")

    harness.runner.open_pr = gone

    outcome = harness.run(base="spec/add-marker/0")

    stored = harness.store.get(unit().id)
    assert outcome.status == "held"
    assert stored.state == PLANNED
    assert stored.resume_from == RESTACK

    other = Harness(tmp_path / "other")

    def refused(unit, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
        raise RuntimeError("gh pr create failed: validation failed")

    other.runner.open_pr = refused

    with pytest.raises(RuntimeError, match="validation failed"):
        other.run()
    assert other.store.get(unit().id).resume_from != RESTACK


def test_a_tier_two_unit_moved_cleanly_runs_tier_two_again_and_posts_for_the_moved_commit(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path, tier="tier2")
    harness.move_result = CLEAN
    (tmp_path / "tree" / "scripts").mkdir(parents=True)
    (tmp_path / "tree" / "scripts" / "dev-stack.sh").write_text("#!/bin/sh\n")
    statuses: list[str] = []
    ran: list[str] = []

    def run(command, **kwargs):
        ran.append(command[-1])
        return subprocess.CompletedProcess(command, 0, "5 passed in 1.00s", "")

    # The real session: it refuses a status for a commit it did not run against.
    session = Tier2Session(
        harness.unit,
        lock=tmp_path / "t2.lock",
        run=run,
        sha=lambda cwd: harness.head(cwd),
        status=lambda repo, result: statuses.append(result.sha),
    )
    harness.runner.run_tier2 = session.run
    harness.runner.post_status = session.post
    harness.runner.push = lambda branch, *, cwd: harness.head(cwd)

    outcome = harness.run()

    assert outcome.status == "open"
    assert harness.store.get(harness.unit.id).state == IN_REVIEW
    assert ran.count("test") == 2, "tier 2 ran before the move and again after it"
    assert statuses == [MOVED], "the status is for the commit that was pushed and re-tested"


def test_tier_two_failing_after_a_clean_move_holds_the_unit_with_its_output(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path, tier="tier2")
    harness.move_result = CLEAN
    answers = iter([(True, "## before"), (False, "FAILED live_test - trunk renamed the route")])

    def tier2(*, cwd: Path) -> tuple[bool, str]:
        harness.events.append("tier2")
        return next(answers)

    harness.runner.run_tier2 = tier2
    harness.close_window_after_one_run()

    outcome = harness.run()

    stored = harness.store.get(harness.unit.id)
    assert outcome.status == "paused"
    assert "push" not in harness.events and "pr" not in harness.events
    assert stored.state == PLANNED
    assert "trunk renamed the route" in stored.feedback


def test_a_forge_that_cannot_be_asked_leaves_the_unit_on_its_base_and_is_logged(
    tmp_path: Path,
) -> None:
    harness = Harness(tmp_path)

    def unreachable(unit, base: str) -> str:
        raise RuntimeError("gh: HTTP 502 from api.example.test")

    harness.runner.fresh_base = unreachable

    outcome = harness.run(base="spec/add-marker/0")

    assert outcome.status == "open"
    assert harness.opened_on == ["spec/add-marker/0"], "opened on the base the run had"
    assert any("HTTP 502" in line for line in harness.recorder.logged)
