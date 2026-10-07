"""The classic runner's scenarios for adapt, tier 2, satisfied, escalations,
holds, spent rounds and moved bases, run through the graph engine with the same
injected fakes (docs/unit-graph.md, Testing): each reaches the same outcome,
state and pull request as `UnitRunner.run`.

Scenarios that end in a wait for the usage window, an event or a person belong
to the waits-and-events group of the change and are not ported here.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.forges.base import BaseMissing
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.convert import convert_units_in_flight
from agent_build_kit.graph.unit import run_unit
from agent_build_kit.pipeline.restack import HostMoved
from agent_build_kit.pipeline.stack_runner import Restacked
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource, UnitStore
from agent_build_kit.pipeline.units import (
    HELD,
    IN_REVIEW,
    PLANNED,
    SATISFIED,
    branch_name,
    waiting_on,
)
from tests.classic_store import leave_in_flight
from tests.factories import unit
from tests.graph.test_build_path import build, limited, once, restacked
from tests.graph_driver import position
from tests.runner_fakes import Recorder, make_runner, rejecting


def fresh(tmp_path: Path, *, tier: str = "tier1", **options: Any) -> Recorder:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(tier=tier)])
    return Recorder(store, **options)


def tasks_file(tmp_path: Path) -> Path:
    tasks = tmp_path / "meta" / "openspec" / "changes" / "add-marker" / "tasks.md"
    tasks.parent.mkdir(parents=True)
    tasks.write_text("## 1. [app] [tier1] G\n- [ ] 1.1 Test: a\n- [ ] 1.2 Do a\n")
    return tasks


def verdict(feedback: str, **fields: Any) -> str:
    return json.dumps({"approved": False, "feedback": feedback, **fields})


def capturing(recorder: Recorder, bodies: list[dict[str, str]]) -> Callable[..., int]:
    """An `open_pr` that keeps the bodies it was given."""

    def open_pr(u: Any, *, body: str, base: str, cwd: Path, **more: str) -> int:
        bodies.append({"body": body, **more})
        return recorder.open_pr(u, body=body, base=base, cwd=cwd)

    return open_pr


# --- tier 2 -------------------------------------------------------------------


def test_tier_two_runs_after_the_review_and_before_the_push_for_a_tier_two_unit(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, tier="tier2")

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    assert recorder.events.count("tier2") == 1
    assert recorder.events.index("review") < recorder.events.index("tier2")
    assert recorder.events.index("tier2") < recorder.events.index("push")


def test_a_failing_tier_two_leaves_no_pull_request_and_keeps_its_output(tmp_path: Path) -> None:
    recorder = fresh(tmp_path, tier="tier2", tier2_ok=False)
    recorder.tier2_output = "FAILED live_test - the route 404s"

    outcome = build(tmp_path, recorder)

    assert "tier2" in recorder.events
    assert outcome.status == "failed"
    assert "tier 2 failed" in outcome.detail
    assert "push" not in recorder.events and "pr" not in recorder.events
    stored = recorder.store.get(unit().id)
    assert stored.state == "failed"
    assert "the route 404s" in stored.feedback


def test_a_tier_two_unit_is_held_at_the_boundary_before_tier_two(tmp_path: Path) -> None:
    """Its upstream went back while it was in review: the live stack is not
    brought up against a stale base."""
    recorder = fresh(tmp_path, tier="tier2", tier2_ok=False)

    outcome = build(
        tmp_path,
        recorder,
        upstream_incomplete=lambda u: (
            (Cause.UPSTREAM_WENT_BACK, "upstream reworking")
            if "review" in recorder.events
            else None
        ),
    )

    assert outcome.status == "held"
    assert "tier2" not in recorder.events
    assert recorder.store.get(unit().id).state == PLANNED


def test_tier_two_follows_checks_that_were_fixed_first(tmp_path: Path) -> None:
    """No point occupying the one local stack to re-confirm a known failure."""
    recorder = fresh(tmp_path, tier="tier2")
    recorder.tier1_results = [(False, "ERROR lint"), (True, "")]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    steps = [e for e in recorder.events if e in ("tier1", "claude:fix_checks", "tier2", "review")]
    assert steps == ["tier1", "claude:fix_checks", "tier1", "review", "tier2"]


def test_the_status_is_posted_after_the_push_and_the_snapshot_reaches_the_body(
    tmp_path: Path,
) -> None:
    """GitHub only accepts a status for a commit it already has."""
    recorder = fresh(tmp_path, tier="tier2")
    recorder.tier2_output = "## Tier 2 results\n5 passed in the live stack"
    bodies: list[dict[str, str]] = []

    build(tmp_path, recorder, open_pr=capturing(recorder, bodies))

    assert recorder.events.index("push") < recorder.events.index("status")
    assert recorder.events.count("status") == 1
    assert "5 passed in the live stack" in bodies[-1]["body"]


def test_a_tier_two_unit_moved_cleanly_runs_tier_two_again_before_it_is_pushed(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, tier="tier2")
    moves = Moves(recorder, CLEAN)

    outcome = build(tmp_path, recorder, **moves.overrides())

    assert outcome.status == "open"
    assert recorder.events.count("tier2") == 2, "before the move and again on the moved commit"
    assert recorder.events.count("status") == 1
    assert recorder.events.index("push") < recorder.events.index("status")


# --- satisfied ----------------------------------------------------------------


def empty_branch(**overrides: Any) -> dict[str, Any]:
    return {"branch_commits": lambda cwd, base: 0, **overrides}


def test_a_unit_with_nothing_of_its_own_and_passing_checks_is_satisfied(tmp_path: Path) -> None:
    """A predecessor did the work: nothing for this unit to add, and what is
    already there passes. Judged from the branch and the checks, never from
    anything the run says about itself."""
    tasks = tasks_file(tmp_path)
    recorder = fresh(tmp_path, commits_from_impl=0)

    outcome = build(tmp_path, recorder, **empty_branch())

    assert outcome.status == "satisfied"
    assert "tier1:whole_repo" in recorder.events
    assert "pr" not in recorder.events and "push" not in recorder.events
    assert "close" not in recorder.events, "there was never a pull request to close"
    assert recorder.store.get(unit().id).state == SATISFIED
    assert tasks.read_text().count("- [x]") == 2, "its groups are ticked all the same"
    dependent = unit(uid="add-marker/2", depends_on=(unit().id,))
    assert waiting_on(dependent, [recorder.store.get(unit().id)]) == []


def test_a_satisfied_units_thread_is_gone(tmp_path: Path) -> None:
    """A thread exists until the unit merges, is closed or is satisfied."""
    recorder = fresh(tmp_path, commits_from_impl=0)
    runner = make_runner(recorder.store, recorder, tmp_path, **empty_branch())

    async def go() -> object:
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            await run_unit(
                runner, recorder.store.get(unit().id), base="main", graph=[], saver=saver
            )
            return await saver.aget_tuple({"configurable": {"thread_id": unit().id}})

    assert asyncio.run(go()) is None


def test_a_satisfied_unit_posts_the_reason_before_closing_its_open_pull_request(
    tmp_path: Path,
) -> None:
    """A rework that finds the work has landed elsewhere in the meantime leaves
    an open pull request with no diff and no future. Reached from feedback
    waiting on an open PR: nothing goes through the tests or implementation."""
    tasks_file(tmp_path)
    recorder = fresh(tmp_path, commits_from_impl=0)
    store = recorder.store
    store.set_state(unit().id, PLANNED, pr=4, branch=branch_name(unit()))
    store.set_feedback(unit().id, "please double-check the edge case")
    # An older version left replies and the comments they answer; they move onto the thread.
    leave_in_flight(
        store, unit().id, pending_replies=["done"], person_comments="[comment 1] rename"
    )

    async def convert() -> None:
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            await convert_units_in_flight(saver, store)

    asyncio.run(convert())
    seeded = position(tmp_path).state
    assert seeded is not None
    assert seeded.pending_replies == ("done",)

    outcome = build(tmp_path, recorder, graph=[store.get(unit().id)], **empty_branch())

    assert outcome.status == "satisfied"
    stored = store.get(unit().id)
    assert stored.feedback == "", "a satisfied unit carries no review feedback"
    # The thread ends with the unit, taking the replies and the comments with it.
    assert position(tmp_path).state is None, "no replies to a review it no longer has"
    assert recorder.events.count("reply") == 0
    assert recorder.events.count("claude:rework") == 1
    for step in ("claude:tests", "claude:impl", "review"):
        assert step not in recorder.events
    assert recorder.events.count("close") == 1
    (unit_id, pr, reason) = recorder.closed[0]
    assert (unit_id, pr) == (unit().id, 4)
    assert "Task group(s) 1" in reason and "implemented elsewhere" in reason.lower()


def test_a_failure_to_close_a_satisfied_units_pull_request_is_recorded_and_leaves_it_satisfied(
    tmp_path: Path,
) -> None:
    """The judgement rests on the branch and the checks; a stale pull request
    that refuses to close is a nuisance, not a reason to revisit it."""
    tasks_file(tmp_path)
    recorder = fresh(tmp_path, commits_from_impl=0, close_error="404 gone")
    recorder.store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))

    outcome = build(tmp_path, recorder, graph=[recorder.store.get(unit().id)], **empty_branch())

    stored = recorder.store.get(unit().id)
    assert outcome.status == "satisfied"
    assert stored.state == SATISFIED
    assert any("404 gone" in message for message in recorder.logged)
    assert "404 gone" in stored.history[-1]["note"]


def test_a_satisfied_unit_releases_its_dependents_before_its_pull_request_is_closed(
    tmp_path: Path,
) -> None:
    """A dependent left on the branch while its pull request closes would be
    closed with it; the worktree and branch go last, once the run has left."""
    tasks_file(tmp_path)
    recorder = fresh(tmp_path, commits_from_impl=0)
    recorder.store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))
    order: list[str] = []

    def release(unit) -> list[str]:
        order.append(f"release {unit.id}")
        return []

    outcome = build(
        tmp_path,
        recorder,
        graph=[recorder.store.get(unit().id)],
        release_dependents=release,
        close_pr=lambda unit, pr, reason: order.append(f"close #{pr}"),
        remove_satisfied=lambda unit: order.append(f"remove {unit.id}"),
        **empty_branch(),
    )

    assert outcome.status == "satisfied"
    assert order == [f"release {unit().id}", "close #4", f"remove {unit().id}"]


def test_a_dependent_that_could_not_be_moved_is_recorded_on_the_satisfied_unit(
    tmp_path: Path,
) -> None:
    tasks_file(tmp_path)
    recorder = fresh(tmp_path, commits_from_impl=0)

    build(
        tmp_path,
        recorder,
        release_dependents=lambda unit: ["add-marker/3 not moved off spec/x — host refused"],
        **empty_branch(),
    )

    stored = recorder.store.get(unit().id)
    assert stored.state == SATISFIED
    assert "add-marker/3" in stored.note and "host refused" in stored.note


def test_nothing_asks_an_agent_anything_once_the_checks_have_judged_an_empty_branch(
    tmp_path: Path,
) -> None:
    tasks_file(tmp_path)
    recorder = fresh(tmp_path, commits_from_impl=0)
    recorder.store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))
    recorder.store.set_feedback(unit().id, "please double-check the edge case")

    outcome = build(tmp_path, recorder, graph=[recorder.store.get(unit().id)], **empty_branch())

    assert outcome.status == "satisfied"
    assert "review" not in recorder.events, "no review round runs for an empty branch"
    after = recorder.events[recorder.events.index("tier1:whole_repo") + 1 :]
    assert not any(e.startswith("claude") or e == "review" for e in after)


# --- review escalations and holds ----------------------------------------------


def test_a_change_only_a_person_can_make_holds_the_unit_instead_of_spending_rounds(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [verdict("exclude the file from check-yaml", needs_human=True)]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "held"
    assert recorder.events.count("review") == 1, "no further rounds"
    assert "claude:rework" not in recorder.events
    stored = recorder.store.get(unit().id)
    assert stored.state == HELD
    assert stored.feedback == "exclude the file from check-yaml"
    assert stored.held_by == "review"
    assert "push" not in recorder.events


def test_an_open_ended_class_holds_the_unit_with_the_reasoning(tmp_path: Path) -> None:
    reasoning = "a list of spellings for a push cannot be complete. The approach needs changing."
    recorder = fresh(tmp_path)
    recorder.verdicts = [
        rejecting("`git -c x=y push` bypasses the pattern"),
        verdict("`git push 'HEAD:main'` bypasses it", escalate="class", reasoning=reasoning),
    ]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "held"
    assert recorder.events.count("review") == 2, "no round spent on the next instance"
    assert recorder.events.count("claude:rework") == 1
    stored = recorder.store.get(unit().id)
    assert stored.state == HELD
    assert reasoning in stored.feedback
    assert stored.held_by == "review"
    assert "The approach needs changing" in stored.history[-1]["note"]
    assert stored.approved == ""
    assert "push" not in recorder.events


def test_a_point_raised_again_after_the_builder_declined_it_holds_the_unit(
    tmp_path: Path,
) -> None:
    builder = "Declined: the registry is only touched from the tick's thread."
    reviewer = "The poller also writes the registry, from its own thread."
    recorder = fresh(tmp_path, rework_answer=builder)
    recorder.verdicts = [
        rejecting("Guard the registry with a lock."),
        verdict("Guard the registry with a lock.", escalate="disagreement", reasoning=reviewer),
    ]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "held"
    assert recorder.events.count("review") == 2, "no third exchange"
    stored = recorder.store.get(unit().id)
    assert stored.state == HELD
    assert builder in stored.feedback and reviewer in stored.feedback
    assert stored.held_by == "review"
    assert "disagree" in stored.history[-1]["note"].lower()
    assert stored.approved == ""


# --- spent rounds ---------------------------------------------------------------


def test_spent_rounds_push_the_branch_report_the_points_and_hold_the_unit(
    tmp_path: Path,
) -> None:
    """Work that exists and whose open points are written down: the branch is
    pushed and its pull request carries the points, so a person inherits a
    branch and a list. Nothing is approved and no task is ticked."""
    from agent_build_kit.config import active

    tasks = tasks_file(tmp_path)
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("the lock is still not released")] * 20
    bodies: list[dict[str, str]] = []

    outcome = build(tmp_path, recorder, open_pr=capturing(recorder, bodies))

    rounds = active().limits.max_review_rounds
    assert outcome.status == "held"
    assert recorder.events.count("review") == rounds
    assert recorder.events.count("tier1") == rounds, "checked before each round, not after"
    stored = recorder.store.get(unit().id)
    assert (stored.state, stored.pr) == (HELD, 7)
    assert "rounds spent" in stored.history[-1]["note"]
    assert stored.held_by == "review"
    assert "the lock is still not released" in stored.feedback
    assert stored.approved == ""
    assert len(recorder.remote) == 1, "pushed though never approved, for a person to inherit"
    assert "the lock is still not released" in bodies[-1]["body"]
    assert "Stacked on" not in bodies[-1]["stacked_body"]
    assert "the lock is still not released" in bodies[-1]["stacked_body"]
    assert "- [x]" not in tasks.read_text()


def test_a_unit_whose_rounds_ran_out_on_a_branch_the_host_moved_is_still_held(
    tmp_path: Path,
) -> None:
    """The adoption is recorded, so a second push holds: the open points reach
    the pull request rather than the unit failing with an empty note."""
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("the lock is still not released")] * 20
    pushes: list[int] = []

    def push(branch: str, *, cwd: Path) -> str:
        pushes.append(1)
        if len(pushes) == 1:
            raise HostMoved("the host moved the branch; adopted its head")
        return recorder.push(branch, cwd=cwd)

    outcome = build(tmp_path, recorder, push=push)

    assert outcome.status == "held"
    stored = recorder.store.get(unit().id)
    assert (stored.state, stored.pr) == (HELD, 7)
    assert len(pushes) == 2


def test_an_unreadable_verdict_does_not_pass_the_branch(tmp_path: Path) -> None:
    """A reviewer whose answer cannot be parsed has not approved anything. The
    rounds run out with the branch never approved: a hold, not a failure."""
    recorder = fresh(tmp_path)
    recorder.verdicts = ["I think it looks fine, honestly"] * 20

    outcome = build(tmp_path, recorder)

    assert outcome.status == "held"
    stored = recorder.store.get(unit().id)
    assert stored.approved == ""
    assert "not readable as a verdict" in stored.feedback


# --- a push the host moved --------------------------------------------------------


def test_a_branch_the_host_moved_is_re_reviewed_rather_than_pushed(tmp_path: Path) -> None:
    """The push step found the host's head is not what was last pushed and
    adopted it: the unit goes back through review, and no pull request is touched."""
    recorder = fresh(tmp_path, push_raises=HostMoved("the host moved it"))

    outcome = build(tmp_path, recorder)

    assert outcome.status == "held"
    assert "re-reviewing" in outcome.detail and "the host moved it" in outcome.detail
    assert "pr" not in recorder.events
    assert recorder.store.get(unit().id).state == PLANNED


# --- holds at a node's boundary ----------------------------------------------------


def test_a_unit_stops_when_its_upstream_goes_back_for_rework(tmp_path: Path) -> None:
    """Carrying on reviewing and pushing against a base that is about to change
    spends the window on work that may need redoing."""
    recorder = fresh(tmp_path)

    outcome = build(
        tmp_path,
        recorder,
        base="spec/add-marker/0",
        upstream_incomplete=lambda u: (
            Cause.UPSTREAM_WENT_BACK,
            "add-marker/0 went back for rework",
        ),
    )

    assert outcome.status == "held"
    assert "went back for rework" in outcome.detail
    assert "push" not in recorder.events and "pr" not in recorder.events
    stored = recorder.store.get(unit().id)
    assert stored.state == PLANNED, "`planned` is what the dependency check gates on"
    assert "held" in str(stored.history[-1])


def test_a_held_unit_finishes_the_step_it_was_in(tmp_path: Path) -> None:
    """The build runs and commits; the hold happens at the boundary."""
    recorder = fresh(tmp_path)

    build(
        tmp_path,
        recorder,
        upstream_incomplete=lambda u: (Cause.UPSTREAM_WENT_BACK, "upstream reworking"),
    )

    assert "commit:test" in recorder.events, "the tests step's work is committed, not discarded"
    assert "claude:impl" not in recorder.events, "and the next step does not start"


def test_a_unit_whose_parent_merged_while_it_built_stops_before_pushing(tmp_path: Path) -> None:
    """The merge leaves a building branch where it is, so the build must notice
    itself: stopping lets the restack put it on its new base first."""
    recorder = fresh(tmp_path)

    outcome = build(
        tmp_path,
        recorder,
        base="spec/add-marker/0",
        base_moved=lambda u, base, **kw: (
            Cause.BASE_CHANGED,
            f"its base moved from {base} to main while it built",
        ),
    )

    assert outcome.status == "held"
    assert "its base moved from spec/add-marker/0 to main" in outcome.detail
    assert "push" not in recorder.events and "pr" not in recorder.events
    assert recorder.store.get(unit().id).state == PLANNED


def test_a_unit_whose_base_was_rewritten_while_it_built_stops_before_pushing(
    tmp_path: Path,
) -> None:
    """Its parent was restacked mid-pass, so the base keeps its name but not
    the commits this unit sits on. The check is against the tip the run
    started on."""
    recorder = fresh(tmp_path)
    seen: list[tuple[Path, str]] = []

    def base_moved(u: Any, base: str, *, tree: Path, start: str) -> tuple[Cause, str] | None:
        seen.append((tree, start))
        # The restack lands while the review runs, after implement.
        if "review" in recorder.events:
            return Cause.BASE_CHANGED, "its base spec/add-marker/0 was rewritten"
        return None

    outcome = build(
        tmp_path,
        recorder,
        base="spec/add-marker/0",
        base_tip=lambda tree, ref: f"tip of {ref}",
        base_moved=base_moved,
    )

    assert "claude:impl" in recorder.events, "implement ran before the rewrite"
    assert outcome.status == "held"
    assert "rewritten" in outcome.detail
    assert "push" not in recorder.events and "pr" not in recorder.events
    assert recorder.store.get(unit().id).state == PLANNED
    assert seen and all(s == (tmp_path / "tree", "tip of spec/add-marker/0") for s in seen)


def test_the_bases_tip_is_recorded_before_a_resume_restacks(tmp_path: Path) -> None:
    """The tip the build is placed on, not the one after the restack: taken
    later, a base rewritten during the restack would be the tip compared
    against, and every check would pass."""
    recorder = fresh(tmp_path)

    build(
        tmp_path,
        recorder,
        base="spec/add-marker/0",
        branch_commits=lambda cwd, base: 2,
        base_tip=lambda tree, ref: recorder.events.append("base_tip") or "t",
        restack_onto=lambda **kw: recorder.events.append("restack") or None,
    )

    assert recorder.events.index("base_tip") < recorder.events.index("restack")


# --- adapt ----------------------------------------------------------------------------

OLD_REF = "refs/spec-driven/pre-adapt/add-marker/1"
RETIRED = "the predecessor made console capture opt-in, so this is moot"


def decisions(*entries: tuple[str, str, str]) -> str:
    return json.dumps(
        {
            "tests": [
                {"name": name, "decision": decision, "reason": reason}
                for name, decision, reason in entries
            ],
            "summary": "ported",
        }
    )


class Adapting:
    """The fakes an adapt needs: a restack that conflicts once, a reset that is
    recorded, and a port that answers from `answers` in order."""

    def __init__(
        self,
        recorder: Recorder,
        answers: list[str],
        *,
        old_tests: tuple[str, ...],
        present: set[str],
        changed: set[str] | None = None,
        always: bool = False,
    ) -> None:
        self.recorder = recorder
        self.answers = answers
        self.present = present
        self.changed = changed or set()
        self.old_tests = old_tests
        self.always = always
        self.prompts: list[str] = []
        self.resets: list[tuple[str, str]] = []
        self.changed_asked_after_commit: list[bool] = []

    def run_rework(
        self,
        prompt: str,
        *,
        cwd: Path,
        resume_session: str = "",
        on_session: object = None,
        on_result: object = None,
    ) -> str:
        self.prompts.append(prompt)
        return self.answers[min(len(self.prompts), len(self.answers)) - 1]

    def tests_in(self, tree: Path) -> set[str]:
        # Nothing of the unit's own is in the tree right after the reset.
        return self.present if self.prompts else set()

    def tests_changed(self, tree: Path, ref: str) -> set[str]:
        self.changed_asked_after_commit.append("commit:adapt" in self.recorder.events)
        return self.changed

    def overrides(self) -> dict[str, Any]:
        conflict = restacked(conflict="x", old_tests=self.old_tests)
        return {
            "branch_commits": lambda cwd, base: 2 + self.recorder.made,
            "restack_onto": (lambda **kw: conflict) if self.always else once(conflict),
            "reset_to": lambda tree, onto, keep: self.resets.append((onto, keep)),
            "tests_in": self.tests_in,
            "tests_changed": self.tests_changed,
            "run_rework": self.run_rework,
        }


def reviewers(recorder: Recorder) -> tuple[list[str], dict[str, Any]]:
    who: list[str] = []

    def named(name: str) -> Callable[..., str]:
        def review(
            *,
            cwd: Path,
            context: str = "",
            resume_session: str = "",
            on_session: object = None,
            on_result: object = None,
        ) -> str:
            who.append(name)
            return recorder.review(cwd=cwd, context=context)

        return review

    return who, {"run_review": named("standard"), "run_rework_review": named("rework")}


def test_a_restack_that_could_not_be_merged_is_ported_and_its_tests_accounted_for(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    who, review = reviewers(recorder)
    answer = decisions(("test_click", "keep", ""), ("test_console", "retire", RETIRED))
    adapting = Adapting(
        recorder,
        [answer],
        old_tests=("test_click", "test_console"),
        present={"test_click"},
    )

    outcome = build(tmp_path, recorder, base="spec/c/2", **adapting.overrides(), **review)

    assert adapting.resets == [("spec/c/2", OLD_REF)]
    assert "`test_console`" in adapting.prompts[0], "the port is told which tests to account for"
    assert "commit:adapt" in recorder.events
    assert "test_console`: retire — " + RETIRED in recorder.contexts[0]
    assert who == ["rework"], "the port is judged by the rework reviewer"
    assert outcome.status == "open"


def test_a_port_that_silently_drops_a_test_fails(tmp_path: Path) -> None:
    """The thing the accounting exists for: a port can end a conflict by
    leaving out what it could not carry over."""
    recorder = fresh(tmp_path)
    adapting = Adapting(
        recorder,
        [decisions(("test_click", "keep", ""))],
        old_tests=("test_click", "test_console", "test_drag"),
        present={"test_click"},
        always=True,
    )

    outcome = build(tmp_path, recorder, base="spec/c/2", **adapting.overrides())

    assert "commit:adapt" in recorder.events
    assert outcome.status == "failed"
    feedback = recorder.store.get(unit().id).feedback
    assert "no decision for `test_console`" in feedback
    assert "outstanding: `test_console`, `test_drag`" in feedback
    assert "push" not in recorder.events


def test_a_test_the_replay_left_alone_is_not_required_in_the_accounting(tmp_path: Path) -> None:
    """The runner can see for itself that a test is present and untouched, so
    the agent is not asked to restate it."""
    recorder = fresh(tmp_path)
    adapting = Adapting(
        recorder,
        [decisions(("test_console", "retire", RETIRED))],
        old_tests=("test_click", "test_console"),
        present={"test_click"},
    )

    outcome = build(tmp_path, recorder, base="spec/c/2", **adapting.overrides())

    assert outcome.status == "open", "test_click needed no decision, so nothing was missing"
    assert "counted as kept without being asked about" in recorder.contexts[0]
    assert "`test_click`" in recorder.contexts[0]
    assert "`test_console`: retire" in recorder.contexts[0]


def test_a_changed_test_still_requires_a_decision_and_is_read_after_the_port(
    tmp_path: Path,
) -> None:
    """A test that survived the replay by name only — present, but weakened —
    still needs an accounting, read against the old work's own ref."""
    recorder = fresh(tmp_path)
    adapting = Adapting(
        recorder,
        [json.dumps({"tests": []})],
        old_tests=("test_click",),
        present={"test_click"},
        changed={"test_click"},
    )

    outcome = build(tmp_path, recorder, base="spec/c/2", **adapting.overrides())

    assert adapting.changed_asked_after_commit and all(adapting.changed_asked_after_commit)
    assert outcome.status == "failed"
    assert "no decision for `test_click`" in recorder.store.get(unit().id).feedback
    assert "test_click" in adapting.prompts[1], "the follow-up names it"


def test_an_unaccounted_test_keeps_where_the_waiting_feedback_came_from(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.store.set_feedback(
        unit().id, "tier 1 failed:\nE assert 1 == 2", source=FeedbackSource.TIER1
    )
    adapting = Adapting(
        recorder,
        [json.dumps({"tests": []})],
        old_tests=("test_click",),
        present={"test_click"},
        changed={"test_click"},
    )

    build(tmp_path, recorder, base="spec/c/2", **adapting.overrides())

    stored = recorder.store.get(unit().id)
    assert "no decision for `test_click`" in stored.feedback
    assert stored.feedback_source is FeedbackSource.TIER1


def test_an_incomplete_accounting_is_asked_again_before_the_unit_fails(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    adapting = Adapting(
        recorder,
        [
            decisions(("test_click", "keep", "")),
            decisions(("test_click", "keep", ""), ("test_console", "retire", RETIRED)),
        ],
        old_tests=("test_click", "test_console"),
        present={"test_click"},
    )

    outcome = build(tmp_path, recorder, base="spec/c/2", **adapting.overrides())

    assert len(adapting.prompts) == 2, "asked again rather than failed on the first miss"
    assert "test_console" in adapting.prompts[1], "told which decision was outstanding"
    assert recorder.events.count("commit:adapt") == 1, "the ported code is not rebuilt for the ask"
    assert outcome.status == "open"


def test_an_accounting_still_incomplete_after_the_last_attempt_fails_the_unit(
    tmp_path: Path,
) -> None:
    limited(max_adapt_rounds=2)
    recorder = fresh(tmp_path)
    adapting = Adapting(
        recorder,
        [decisions(("test_click", "keep", ""))],
        old_tests=("test_click", "test_console"),
        present={"test_click"},
        always=True,
    )

    outcome = build(tmp_path, recorder, base="spec/c/2", **adapting.overrides())

    assert outcome.status == "failed"
    assert len(adapting.prompts) == 2, "asked again up to the bound, then stopped"
    assert "no decision for `test_console`" in recorder.store.get(unit().id).feedback
    assert "push" not in recorder.events


def test_a_changed_test_answered_keep_is_asked_again(tmp_path: Path) -> None:
    """The pipeline measured `test_click` as different from the old work, so the
    agent saying it is unchanged does not stand."""
    recorder = fresh(tmp_path)
    adapting = Adapting(
        recorder,
        [
            decisions(("test_click", "keep", "")),
            decisions(("test_click", "adapt", "dropped the console assertion to fit")),
        ],
        old_tests=("test_click",),
        present={"test_click"},
        changed={"test_click"},
    )

    outcome = build(tmp_path, recorder, base="spec/c/2", **adapting.overrides())

    assert outcome.status == "open"
    assert "differs from the previous work" in adapting.prompts[1]


def test_follow_up_decisions_are_merged_over_the_first_answers(tmp_path: Path) -> None:
    """An agent that only answers for the tests just named must not lose the
    decisions it already gave."""
    recorder = fresh(tmp_path)
    adapting = Adapting(
        recorder,
        [
            decisions(("test_click", "retire", RETIRED)),
            decisions(("test_console", "retire", RETIRED)),
        ],
        old_tests=("test_click", "test_console"),
        present=set(),
    )

    outcome = build(tmp_path, recorder, base="spec/c/2", **adapting.overrides())

    assert outcome.status == "open"


def test_a_base_rewritten_while_a_resume_adapts_holds_the_build(tmp_path: Path) -> None:
    """The adapt runs a model for minutes. A parent restacked meanwhile rewrites
    the base under the same name, and the unit, reset onto the old tip, would
    push the parent's pre-rebase commits."""
    recorder = fresh(tmp_path)
    tip = ["before"]
    adapting = Adapting(
        recorder,
        [decisions(("test_click", "keep", ""))],
        old_tests=("test_click",),
        present={"test_click"},
    )
    overrides: dict[str, Any] = adapting.overrides()
    port = overrides["run_rework"]

    def adapt(
        prompt: str,
        *,
        cwd: Path,
        resume_session: str = "",
        on_session: object = None,
        on_result: object = None,
    ) -> str:
        tip[0] = "rewritten"  # the parent is restacked while the port runs
        return port(prompt, cwd=cwd, resume_session=resume_session, on_session=on_session)

    wired: dict[str, Any] = {**overrides, "run_rework": adapt}
    outcome = build(
        tmp_path,
        recorder,
        base="spec/add-marker/0",
        **wired,
        base_tip=lambda tree, ref: tip[0],
        base_moved=lambda u, base, *, tree, start: (
            (Cause.BASE_CHANGED, f"its base {base} was rewritten") if start != tip[0] else None
        ),
    )

    assert tip == ["rewritten"], "the adapt ran"
    assert outcome.status == "held"
    assert "rewritten" in outcome.detail
    assert "push" not in recorder.events and "pr" not in recorder.events
    assert recorder.store.get(unit().id).state == PLANNED


# --- a base that moves before the push ------------------------------------------------

MOVED = "moved-sha"
CLEAN = restacked()
RESOLVED = restacked(resolved=("a.py",))
CONFLICTED = restacked(conflict="a.py")


class Moves:
    """The base moving under a unit: a restack that answers from `results` once
    review has run, and finds the branch on its base before that."""

    def __init__(self, recorder: Recorder, *results: Restacked | Exception | None) -> None:
        self.recorder = recorder
        self.results = list(results)
        self.resolving: list[bool] = []
        self.moved = False
        # Whether a clean move carries the approval to the moved commit, as the
        # real one does when the unit's own diff is unchanged.
        self.carries_approval = True

    def head(self, cwd: Path) -> str:
        return MOVED if self.moved else self.recorder.head(cwd)

    def restack(self, *, resolve: bool = True, **kw: Any) -> Restacked | None:
        self.resolving.append(resolve)
        if "review" not in self.recorder.events or not self.results:
            return None
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        if result is not None and not result.resolved and not result.conflict:
            self.moved = True
            if self.carries_approval:
                self.recorder.store.record_approval(unit().id, MOVED)
        return result

    def overrides(self, *, existing: int = 0) -> dict[str, Any]:
        found: dict[str, Any] = {"head": self.head, "restack_onto": self.restack}
        if existing:
            found["branch_commits"] = lambda cwd, base: existing + self.recorder.made
        return found


@pytest.mark.parametrize(
    "result",
    [RESOLVED, CONFLICTED, RuntimeError("both sides changed a.py")],
    ids=["resolved", "conflicted", "unresolvable"],
)
def test_a_move_that_needs_resolution_before_the_push_resumes_at_its_restack_at_once(
    tmp_path: Path, result: Restacked | Exception
) -> None:
    recorder = fresh(tmp_path)
    moves = Moves(recorder, result)

    outcome = build(tmp_path, recorder, **moves.overrides(existing=2))

    assert outcome.status == "open", "the same run goes on, rather than queueing"
    assert moves.resolving == [True, False, True, False], "the resumed restack may resolve"
    assert recorder.events.count("push") == 1, "nothing is pushed from the half-resolved branch"


def test_a_base_that_keeps_needing_resolution_is_resumed_once_then_left_planned(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    # The push-time move, the resumed run's own restack, its push-time move.
    moves = Moves(recorder, RESOLVED, None, RESOLVED)

    outcome = build(tmp_path, recorder, **moves.overrides(existing=2))

    stored = recorder.store.get(unit().id)
    assert outcome.status == "held"
    assert "push" not in recorder.events and "pr" not in recorder.events
    assert stored.state == PLANNED
    assert stored.cause == Cause.BASE_CHANGED
    assert moves.resolving.count(False) == 2, "one resume, not a loop"


def test_tier_one_failing_after_a_clean_move_is_reworked_reviewed_and_opened_in_the_same_run(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    moves = Moves(recorder, CLEAN)
    recorder.tier1_results = [
        (True, ""),
        (False, "FAILED test_a - trunk renamed the helper"),
        (True, ""),
    ]

    outcome = build(tmp_path, recorder, **moves.overrides())

    assert outcome.status == "open"
    stored = recorder.store.get(unit().id)
    assert stored.state == IN_REVIEW
    rework = [p for p in recorder.prompts if "trunk renamed the helper" in p]
    assert len(rework) == 1, "the rework was given the tier 1 output"
    after = recorder.events[recorder.events.index("claude:fix_checks") :]
    assert after.index("tier1") < after.index("review") < after.index("push") < after.index("pr")
    assert recorder.events.count("push") == 1, "nothing was pushed before the rework"
    assert stored.feedback == ""


def test_a_clean_move_whose_approval_did_not_carry_is_reviewed_again_not_refused(
    tmp_path: Path,
) -> None:
    """Moved without conflicts, but the unit's diff is not the one review read:
    the commit being pushed is not the approved one. It is read again."""
    recorder = fresh(tmp_path)
    moves = Moves(recorder, CLEAN)
    moves.carries_approval = False

    outcome = build(tmp_path, recorder, **moves.overrides())

    assert outcome.status != "failed", outcome.detail
    assert "refusing to push" not in outcome.detail
    assert recorder.events.count("review") == 2
    assert "push" in recorder.events


def test_a_base_gone_at_open_is_asked_for_again_and_the_unit_goes_on_from_the_new_one(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    base_now = ["spec/add-marker/0"]
    opened: list[str] = []

    def gone(u: Any, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
        opened.append(base)
        if base == "spec/add-marker/0":
            # Merged, and its branch deleted, after the check said otherwise.
            base_now[0] = "main"
            raise BaseMissing("base branch spec/add-marker/0 does not exist")
        return recorder.open_pr(u, body=body, base=base, cwd=cwd)

    outcome = build(
        tmp_path,
        recorder,
        base="spec/add-marker/0",
        branch_commits=lambda cwd, base: 2 + recorder.made,
        fresh_base=lambda u, base: base_now[0],
        open_pr=gone,
    )

    assert outcome.status == "open"
    assert opened == ["spec/add-marker/0", "main"], "the retry is on the merged-to base"
    assert recorder.store.get(unit().id).state == IN_REVIEW


def test_a_base_gone_at_open_that_the_forge_still_names_holds_the_unit(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)

    def gone(u: Any, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
        raise BaseMissing("base branch spec/add-marker/0 does not exist")

    outcome = build(
        tmp_path,
        recorder,
        base="spec/add-marker/0",
        branch_commits=lambda cwd, base: 2 + recorder.made,
        fresh_base=lambda u, base: "spec/add-marker/0",
        open_pr=gone,
    )

    stored = recorder.store.get(unit().id)
    assert outcome.status == "held"
    assert stored.state == PLANNED
    assert "before its pull request" in stored.note, "it was pushed, so not 'before its push'"


@pytest.mark.parametrize("tier", ["tier1", "tier2"])
def test_a_unit_moved_cleanly_onto_the_base_the_forge_named_is_pushed_not_held(
    tmp_path: Path, tier: str
) -> None:
    recorder = fresh(tmp_path, tier=tier)
    moves = Moves(recorder, CLEAN)
    opened: list[str] = []

    def open_pr(u: Any, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
        opened.append(base)
        return recorder.open_pr(u, body=body, base=base, cwd=cwd)

    outcome = build(
        tmp_path,
        recorder,
        base="spec/add-marker/0",
        fresh_base=lambda u, base: "main",
        base_moved=lambda u, base, **kw: (
            None if base == "spec/add-marker/0" else (Cause.BASE_CHANGED, f"moved to {base}")
        ),
        open_pr=open_pr,
        **moves.overrides(),
    )

    assert outcome.status == "open", outcome.detail
    assert recorder.events.count("push") == 1
    assert opened == ["main"]


def test_a_unit_whose_rounds_ran_out_gets_a_fresh_budget_when_its_base_is_gone_at_open(
    tmp_path: Path,
) -> None:
    from agent_build_kit.config import active

    recorder = fresh(tmp_path)
    recorder.verdicts = [
        rejecting("the lock is still not released")
    ] * active().limits.max_review_rounds
    base_now = ["spec/add-marker/0"]

    def gone(u: Any, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
        if base == "spec/add-marker/0":
            base_now[0] = "main"
            raise BaseMissing("base branch spec/add-marker/0 does not exist")
        return recorder.open_pr(u, body=body, base=base, cwd=cwd)

    outcome = build(
        tmp_path,
        recorder,
        base="spec/add-marker/0",
        branch_commits=lambda cwd, base: 2 + recorder.made,
        fresh_base=lambda u, base: base_now[0],
        open_pr=gone,
    )

    stored = recorder.store.get(unit().id)
    assert outcome.status == "open", outcome.detail
    assert stored.state == IN_REVIEW
    assert "rounds spent" not in stored.note
    assert all("rounds spent" not in h.get("note", "") for h in stored.history)


def test_a_tier_two_unit_whose_checks_never_pass_ends_failed_before_tier_two_and_the_push(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, tier="tier2")
    recorder.tier1_results = [(False, "ERROR lint")] * 20

    outcome = build(tmp_path, recorder)

    assert outcome.status == "failed"
    assert "tier2" not in recorder.events and "push" not in recorder.events
