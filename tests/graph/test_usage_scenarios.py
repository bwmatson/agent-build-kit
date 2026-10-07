"""A unit and the usage window, and how many rounds it may spend fixing failing
checks, run through the graph engine (docs/unit-graph.md, Usage pauses).

A usage pause is an interrupt at an agent node's boundary: the unit stays
`running` and its thread keeps what the loop had so far.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import FeedbackSource
from agent_build_kit.pipeline.units import IN_REVIEW, branch_name
from tests.factories import unit
from tests.graph.test_build_path import build, limited
from tests.graph.test_remaining_paths import fresh
from tests.graph_driver import position, tick
from tests.runner_fakes import approving, rejecting

FAILING = "ERROR implicit-any-empty-container\n  --> tests/test_x.py:3:5"


class Gate:
    """A usage guard that says yes a set number of times, then no; counts its reads."""

    def __init__(self, yes: int) -> None:
        self.yes = yes
        self.calls = 0

    def __call__(self) -> tuple[bool, str]:
        self.calls += 1
        self.yes -= 1
        return (self.yes >= 0, "usage fine" if self.yes >= 0 else "session usage at 75%")


# --- an implementation step that adds nothing -----------------------------------


def test_an_empty_step_against_an_exhausted_window_is_a_pause_not_a_failure(
    tmp_path: Path,
) -> None:
    """An agent told it is out of usage can finish a step cleanly having
    written nothing. The tests commit is on the branch, so the unit is not
    failed and not judged empty: the thread waits before its next agent step."""
    recorder = fresh(tmp_path, commits_from_impl=0)
    # Yes for the tests and the implementation, no before the review: the
    # window filled while the implementation ran.
    gate = Gate(2)

    outcome = tick(tmp_path, recorder, may_start=gate)

    assert outcome.status == RunStatus.PAUSED
    assert "75%" in outcome.detail
    stored = recorder.store.get(unit().id)
    assert stored.state == "running", "interrupted: not failed, not put back to planned"
    paused = position(tmp_path)
    assert paused.next == (Node.REVIEW,)
    assert paused.pause is not None and "75%" in paused.pause.reason
    assert "review" not in recorder.events and "push" not in recorder.events
    assert "commit:test" in recorder.events, "the tests commit survives the pause"


def test_the_pause_check_costs_one_read_per_agent_step(tmp_path: Path) -> None:
    """The guard is asked at each agent node's boundary and never while a step
    runs: the tests, the implementation, and the review that is refused."""
    recorder = fresh(tmp_path, commits_from_impl=0)
    gate = Gate(2)

    tick(tmp_path, recorder, may_start=gate)

    assert gate.calls == 3


def test_an_empty_step_is_not_a_pause_when_usage_is_healthy(tmp_path: Path) -> None:
    """The tests step still committed, so the branch carries this unit's own
    work though the implementation added nothing on top: reviewed and pushed
    like any other unit, not judged as if nothing were there at all."""
    recorder = fresh(tmp_path, commits_from_impl=0)

    outcome = tick(tmp_path, recorder)

    assert outcome.status == RunStatus.OPEN
    assert "review" in recorder.events
    stored = recorder.store.get(unit().id)
    assert stored.state == IN_REVIEW
    assert position(tmp_path).pause is None


def test_a_usage_paused_empty_step_resumes_with_its_commits_intact(tmp_path: Path) -> None:
    recorder = fresh(tmp_path, commits_from_impl=0)
    tick(tmp_path, recorder, may_start=Gate(2))

    resumed = tick(tmp_path, recorder)

    assert recorder.events.count("claude:tests") == 1, "the tests commit survived the pause"
    assert recorder.events.count("claude:impl") == 1, "and the implementation is not run again"
    assert resumed.status == RunStatus.OPEN


# --- the loop's history and feedback across a pause -----------------------------


def test_a_pause_between_review_and_rework_keeps_what_review_asked_for(tmp_path: Path) -> None:
    """Stopped after a review asked for changes, the resume makes them, not
    review the same branch again and pay for the same verdict twice."""
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("name it better"), approving()]
    # Yes for the tests, the implementation and the review; no before the rework.
    outcome = tick(tmp_path, recorder, may_start=Gate(3))

    assert outcome.status == RunStatus.PAUSED
    assert recorder.store.get(unit().id).feedback == "name it better"
    paused = position(tmp_path)
    assert paused.next == (Node.REWORK,)
    assert paused.state is not None
    assert paused.state.review_rounds[0]["asked"] == "name it better", "the history survives"

    resumed = tick(tmp_path, recorder)

    assert resumed.status == RunStatus.OPEN
    assert recorder.events.count("claude:rework") == 1
    assert recorder.events.count("review") == 2
    assert "name it better" in recorder.contexts[1], "the later review sees what was asked"


def test_replies_survive_a_pause_between_the_rework_and_the_push(tmp_path: Path) -> None:
    """A rework writes replies to review threads, its review asks for more, the
    unit pauses for usage before the push, and the replies go with the
    process. Kept on the thread, the run that finally pushes posts them."""
    recorder = fresh(tmp_path)
    recorder.made = 2
    recorder.store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))
    recorder.store.set_feedback(unit().id, "[comment 11] a.py:3 - rename", from_person=True)
    recorder.verdicts = [rejecting("and the docs"), approving()]
    posted: list[str] = []

    def reply(**kwargs: Any) -> None:
        posted.append(kwargs["answer_text"])

    # Yes for the rework and its review; no before the loop's rework.
    first = tick(tmp_path, recorder, may_start=Gate(2), reply=reply)

    assert first.status == RunStatus.PAUSED
    assert posted == []
    state = position(tmp_path).state
    assert state is not None and state.pending_replies == ("done",)

    tick(tmp_path, recorder, reply=reply)

    assert posted == ["done"]
    after = position(tmp_path).state
    assert after is None or after.pending_replies == ()


def test_a_loop_rework_answers_the_reviewer_not_the_pull_request(tmp_path: Path) -> None:
    """That feedback is the loop's own reviewer's. Run as pull request
    feedback, its summary would be posted to the pull request, telling the
    person "you asked" for things only the reviewer had."""
    recorder = fresh(tmp_path)
    recorder.store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))
    recorder.verdicts = [rejecting("render it as a tree"), approving()]
    posted: list[str] = []

    tick(tmp_path, recorder, reply=lambda **kwargs: posted.append(kwargs["answer_text"]))

    rework = [p for p in recorder.prompts if "render it as a tree" in p]
    assert len(rework) == 1
    assert rework[0].startswith("A review of this branch asked for changes")
    assert posted == []


# --- the checks before a review: how many fix rounds, and when they count from ----


def test_the_default_is_three_fix_rounds(tmp_path: Path) -> None:
    recorder = fresh(tmp_path, tier1_ok=False)
    recorder.tier1_output = FAILING

    outcome = build(tmp_path, recorder)

    assert outcome.status == "failed"
    assert recorder.events.count("claude:fix_checks") == 3


def test_the_fix_budget_starts_again_for_each_round_of_review(tmp_path: Path) -> None:
    """Per round, not per unit: a rework that breaks the build again is its own
    problem, with its own attempts, and does not inherit a spent budget."""
    limited(max_check_rounds=2)
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("rename it"), approving()]
    recorder.tier1_results = [
        (False, FAILING),  # round 1: two fixes, the whole budget...
        (False, FAILING),
        (True, ""),
        (False, FAILING),  # ...and round 2 gets two more
        (False, FAILING),
        (True, ""),
    ]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    assert recorder.events.count("claude:fix_checks") == 4
    assert recorder.events.count("review") == 2


def test_no_limit_keeps_fixing_until_the_checks_pass(tmp_path: Path) -> None:
    limited(max_check_rounds=None)
    recorder = fresh(tmp_path)
    recorder.tier1_results = [(False, FAILING)] * 12 + [(True, "")]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    assert recorder.events.count("claude:fix_checks") == 12
    assert recorder.events.count("review") == 1


def test_a_pause_while_fixing_keeps_the_failure_for_the_resume(tmp_path: Path) -> None:
    recorder = fresh(tmp_path, tier1_ok=False)
    recorder.tier1_output = FAILING

    outcome = tick(
        tmp_path,
        recorder,
        may_start=lambda: ("tier1" not in recorder.events, "session at 91%"),
    )

    assert outcome.status == RunStatus.PAUSED
    assert position(tmp_path).next == (Node.FIX_CHECKS,)
    assert recorder.store.get(unit().id).feedback_source == FeedbackSource.TIER1
    assert "claude:fix_checks" not in recorder.events

    recorder.tier1_results = [(True, "")]
    resumed = tick(tmp_path, recorder)

    assert resumed.status == RunStatus.OPEN
    fixes = [p for p in recorder.prompts if "checks (lint" in p]
    assert len(fixes) == 1 and FAILING in fixes[0], "the resume fixes this, not a guess"


def test_a_pause_still_stops_an_unlimited_fix_loop(tmp_path: Path) -> None:
    """The usage guard, checked before every fix, is what bounds the cost."""
    limited(max_check_rounds=None)
    recorder = fresh(tmp_path, tier1_ok=False)
    recorder.tier1_output = FAILING

    outcome = tick(
        tmp_path,
        recorder,
        may_start=lambda: (recorder.events.count("claude:fix_checks") < 2, "session at 91%"),
    )

    assert outcome.status == RunStatus.PAUSED
    assert recorder.events.count("claude:fix_checks") == 2
    assert position(tmp_path).next == (Node.FIX_CHECKS,)
