"""The classic runner's build-path scenarios, run through the graph engine
with the same injected fakes (docs/unit-graph.md, Testing): each reaches the
same outcome, state, pull request and commits as `UnitRunner.run`."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import config as config_module
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.unit import run_unit
from agent_build_kit.pipeline.restack import HostMoved
from agent_build_kit.pipeline.stack_runner import Restacked, RunOutcome
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, branch_name
from agent_build_kit.pipeline.usage_guard import Interrupted, RateLimited
from tests.factories import stored_unit, unit
from tests.runner_fakes import Recorder, make_runner, rejecting


def build(
    tmp_path: Path,
    recorder: Recorder,
    *,
    graph: list[StoredUnit] | None = None,
    base: str = "main",
    **overrides: Any,
) -> RunOutcome:
    runner = make_runner(recorder.store, recorder, tmp_path, **overrides)

    async def go() -> RunOutcome:
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            return await run_unit(
                runner,
                recorder.store.get(unit().id),
                base=base,
                graph=graph or [],
                saver=saver,
            )

    return asyncio.run(go())


def fresh(tmp_path: Path, **options) -> Recorder:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    return Recorder(store, **options)


def test_a_unit_runs_tests_first_then_implementation(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)

    build(tmp_path, recorder)

    assert recorder.events[:4] == ["claude:tests", "commit:test", "claude:impl", "commit:feat"]


def test_an_approved_build_is_pushed_and_opened_and_recorded_as_in_review(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    assert outcome.pr == 7
    stored = recorder.store.get(unit().id)
    assert (stored.state, stored.pr, stored.branch) == (IN_REVIEW, 7, "spec/add-marker/1")
    assert recorder.events.count("review") == 1
    assert "claude:rework" not in recorder.events
    assert recorder.events.index("push") < recorder.events.index("pr")
    assert "status" not in recorder.events, "a unit that never ran tier 2 has none to post"


def test_the_checks_run_once_and_before_the_review_and_the_review_before_the_push(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)

    build(tmp_path, recorder)

    assert recorder.events.count("tier1") == 1
    assert recorder.events.index("tier1") < recorder.events.index("review")
    assert recorder.events.index("review") < recorder.events.index("push")


def test_a_rejected_build_is_sent_back_with_the_findings_and_reviewed_again(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("the session registry leaks")]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    assert recorder.events.count("review") == 2
    assert "claude:rework" in recorder.events
    assert "leaks" in " ".join(recorder.prompts)


def test_an_implementation_that_adds_nothing_still_goes_to_review(tmp_path: Path) -> None:
    recorder = fresh(tmp_path, commits_from_impl=0)

    outcome = build(tmp_path, recorder)

    assert "review" in recorder.events
    assert outcome.status == "open"


def test_only_the_approved_commit_is_pushed(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)

    build(tmp_path, recorder)

    assert recorder.remote == [recorder.head(tmp_path)]
    assert recorder.store.get(unit().id).approved == recorder.head(tmp_path)


def test_a_failing_tier_one_fails_the_unit_and_leaves_no_pull_request(tmp_path: Path) -> None:
    recorder = fresh(tmp_path, tier1_ok=False)
    recorder.tier1_output = "E   ImportError: cannot import name 'geo' from 'src'"

    outcome = build(tmp_path, recorder)

    assert outcome.status == "failed"
    assert recorder.store.get(unit().id).state == "failed"
    assert "ImportError" in recorder.store.get(unit().id).feedback
    assert "push" not in recorder.events
    assert recorder.prs == {}


def test_a_second_run_on_a_finished_thread_starts_from_a_clean_state(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    assert build(tmp_path, recorder).pr == 7

    recorder.store.set_feedback(unit().id, "rename it")
    recorder.push_raises = HostMoved("host head moved")
    outcome = build(tmp_path, recorder)

    assert outcome.status == "held"
    assert outcome.pr is None, "the first run's pull request is not this run's"


def test_the_prompts_are_scoped_to_this_unit_and_name_the_change(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    graph = [
        stored_unit("add-marker/1", groups=(1,)),
        stored_unit("add-marker/2", groups=(2, 3), depends_on=("add-marker/1",)),
    ]

    build(tmp_path, recorder, graph=graph)

    assert len(recorder.prompts) == 2, "the tests and the implementation, nothing else"
    for prompt in recorder.prompts:
        assert "/opsx:" not in prompt
        assert "openspec/changes/add-marker" in prompt
        assert "2, 3" in prompt, "the later unit's groups are named"
        assert "later" in prompt.lower()


def test_a_unit_with_feedback_addresses_it_instead_of_starting_over(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.made = 2
    recorder.store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))
    recorder.store.set_feedback(unit().id, "Use a Sequence, list is invariant")

    build(tmp_path, recorder)

    assert len(recorder.prompts) == 1, "one rework, not the tests-then-implementation pair"
    assert "Use a Sequence, list is invariant" in recorder.prompts[0]
    assert recorder.store.get(unit().id).feedback == "", "cleared once addressed"


def test_a_unit_with_work_on_its_branch_and_no_feedback_builds_nothing_more(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, commits_from_impl=0)
    recorder.made = 2

    outcome = build(tmp_path, recorder)

    assert recorder.prompts == [], "no model call at all"
    assert "tier1" in recorder.events
    assert outcome.status == "open"


def test_a_resumed_unit_is_not_reviewed_again_at_the_commit_it_approved(tmp_path: Path) -> None:
    """Nothing was written since, and review approved exactly this commit."""
    recorder = fresh(tmp_path, commits_from_impl=0)
    recorder.made = 2
    recorder.store.record_approval(unit().id, recorder.head(tmp_path))

    build(tmp_path, recorder)

    assert "review" not in recorder.events
    assert "push" in recorder.events


def test_a_branch_review_never_approved_is_reviewed_before_it_is_pushed(tmp_path: Path) -> None:
    recorder = fresh(tmp_path, commits_from_impl=0)
    recorder.made = 2

    build(tmp_path, recorder)

    assert recorder.events.index("review") < recorder.events.index("push")


def test_a_disagreement_the_builder_never_declined_is_an_ordinary_rejection(
    tmp_path: Path,
) -> None:
    """Escalation needs the builder to have declined a point on an earlier round."""
    recorder = fresh(tmp_path, rework_answer="")
    recorder.verdicts = [
        rejecting("rename it"),
        json.dumps({"approved": False, "feedback": "rename it", "escalate": "disagreement"}),
    ]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    assert recorder.events.count("claude:rework") == 2
    assert recorder.events.count("review") == 3


# --- the checks before a review -------------------------------------------------

FAILING = "ERROR implicit-any-empty-container\n  --> tests/test_x.py:3:5"


def limited(**limits: int | None) -> None:
    """The given limits; the suite's autouse fixture puts the config back."""
    current = config_module.active()
    config_module.activate(
        current.model_copy(update={"limits": current.limits.model_copy(update=limits)}),
        config_module.active_root(),
    )


def test_failing_checks_go_back_to_the_builder_before_a_reviewer_is_asked(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.tier1_results = [(False, FAILING), (True, "")]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    steps = [e for e in recorder.events if e in ("tier1", "claude:fix_checks", "review", "push")]
    assert steps == ["tier1", "claude:fix_checks", "tier1", "review", "push"]
    fix = [p for p in recorder.prompts if "checks (lint" in p]
    assert len(fix) == 1 and FAILING in fix[0]
    assert recorder.store.get(unit().id).feedback == "", "the saved failure is cleared"


def test_checks_that_keep_failing_fail_the_unit_before_any_review(tmp_path: Path) -> None:
    limited(max_check_rounds=2)
    recorder = fresh(tmp_path, tier1_ok=False)
    recorder.tier1_output = FAILING

    outcome = build(tmp_path, recorder)

    assert outcome.status == "failed"
    assert "checks still failing after 2 fix round(s)" in outcome.detail
    assert recorder.events.count("claude:fix_checks") == 2, "the budget, no more"
    assert recorder.events.count("tier1") == 3
    assert "review" not in recorder.events and "push" not in recorder.events
    stored = recorder.store.get(unit().id)
    assert stored.state == "failed" and FAILING in stored.feedback


def test_a_budget_of_zero_still_checks_but_makes_no_fix_attempt(tmp_path: Path) -> None:
    limited(max_check_rounds=0)
    recorder = fresh(tmp_path, tier1_ok=False)
    recorder.tier1_output = FAILING

    outcome = build(tmp_path, recorder)

    assert outcome.status == "failed"
    assert recorder.events.count("tier1") == 1
    assert "claude:fix_checks" not in recorder.events
    assert "review" not in recorder.events


def test_a_fix_that_leaves_the_branch_as_it_was_stops_the_run(tmp_path: Path) -> None:
    limited(max_check_rounds=None)
    recorder = fresh(tmp_path, commits_from_impl=0, tier1_ok=False)
    recorder.tier1_output = FAILING

    outcome = build(tmp_path, recorder)

    assert outcome.status == "failed"
    assert "changed nothing" in outcome.detail
    assert recorder.events.count("claude:fix_checks") == 1
    assert "review" not in recorder.events


def test_a_rework_after_review_is_checked_again_before_the_next_review(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("rename it")]
    recorder.tier1_results = [(True, ""), (False, FAILING), (True, "")]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    steps = [
        e for e in recorder.events if e in ("tier1", "claude:fix_checks", "claude:rework", "review")
    ]
    assert steps == [
        "tier1",
        "review",
        "claude:rework",
        "tier1",
        "claude:fix_checks",
        "tier1",
        "review",
    ]


# --- the restack before anything else -------------------------------------------


def restacked(**overrides: Any) -> Restacked:
    fields: dict[str, Any] = {
        "onto_unit": "c/2",
        "onto_intent": "the MCP surface",
        "old_base": "a",
        "old_head": "b",
    }
    return Restacked(**{**fields, **overrides})


def once(result: Restacked) -> Callable[..., Restacked | None]:
    """A restack that moves the branch at the start of the run and finds it
    already on its base when asked again."""
    answers = iter([result])
    return lambda **kw: next(answers, None)


def test_a_resuming_unit_restacks_before_anything_else(tmp_path: Path) -> None:
    """Verifying or reviewing first would judge the unit against a base it does not have."""
    recorder = fresh(tmp_path)
    recorder.made = 2

    moves = once(restacked())

    def restack(**kw: Any) -> Restacked | None:
        recorder.events.append("restack")
        return moves(**kw)

    build(tmp_path, recorder, base="spec/add-marker/0", restack_onto=restack)

    assert recorder.events[0] == "restack", "before the review, the checks and the push"


def test_a_conflicted_restack_fails_the_unit_rather_than_guessing(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.made = 2

    def conflicted(**kw: Any) -> None:
        raise RuntimeError("both sides changed sessions.py")

    outcome = build(tmp_path, recorder, base="spec/add-marker/0", restack_onto=conflicted)

    assert outcome.status == "failed"
    assert "sessions.py" in recorder.store.get(unit().id).feedback
    assert "push" not in recorder.events


def test_a_failed_restack_keeps_the_review_feedback_already_waiting(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.made = 2
    recorder.store.set_feedback(unit().id, "make hover work on non-widgets")

    def conflicted(**kw: Any) -> None:
        raise RuntimeError("the resolution dropped a test")

    build(tmp_path, recorder, base="spec/add-marker/0", restack_onto=conflicted)

    feedback = recorder.store.get(unit().id).feedback
    assert "make hover work on non-widgets" in feedback
    assert "dropped a test" in feedback


@pytest.mark.parametrize(
    "refusal",
    [
        RateLimited("usage limit reached", resets_at=datetime(2030, 1, 1, tzinfo=UTC)),
        Interrupted("claude was killed by signal 15"),
    ],
    ids=["rate-limited", "interrupted"],
)
def test_a_restack_the_resolver_could_not_run_is_not_a_conflict(
    tmp_path: Path, refusal: Exception
) -> None:
    """It reaches the tick, which pauses or reclaims, and the unit is not failed."""
    recorder = fresh(tmp_path)
    recorder.made = 2

    def refused(**kw: Any) -> None:
        raise refusal

    with pytest.raises(type(refusal)):
        build(tmp_path, recorder, base="spec/add-marker/0", restack_onto=refused)

    assert recorder.store.get(unit().id).state != "failed"
    assert "conflicted" not in recorder.store.get(unit().id).feedback


def test_a_restack_that_needed_resolving_is_reviewed_for_whether_its_tests_still_fit(
    tmp_path: Path,
) -> None:
    """A resolver rewrote the unit's code: its tests may now assert behaviour the
    predecessor removed."""
    recorder = fresh(tmp_path)
    recorder.made = 2
    who: list[str] = []

    def reviewer(name: str) -> Callable[..., str]:
        def review(*, cwd: Path, context: str = "") -> str:
            who.append(name)
            return recorder.review(cwd=cwd, context=context)

        return review

    build(
        tmp_path,
        recorder,
        base="spec/c/2",
        restack_onto=once(restacked(resolved=("src/mcp.py",))),
        run_review=reviewer("standard"),
        run_rework_review=reviewer("rework"),
    )

    assert who == ["rework"], "judged by the rework reviewer"
    assert "moved onto an updated predecessor" in recorder.contexts[0]
    assert "src/mcp.py" in recorder.contexts[0]
    assert "check each of this unit's tests" in recorder.contexts[0]
    assert recorder.store.get(unit().id).predecessor_note == "", "cleared once in review"


def test_a_branch_moved_cleanly_before_the_push_is_checked_again_and_the_moved_head_pushed(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.made = 2
    calls: list[int] = []

    def restack(**kw: Any) -> Restacked | None:
        calls.append(1)
        if len(calls) != 2:
            return None
        # The base moved after review approved; the move is clean, so the
        # approval is re-recorded at the moved head, as the real restack does.
        recorder.made += 1
        recorder.store.record_approval(unit().id, recorder.head(tmp_path))
        return restacked()

    def fresh_base(u: Any, base: str) -> str:
        recorder.events.append("verify_base")
        return base

    outcome = build(tmp_path, recorder, restack_onto=restack, fresh_base=fresh_base)

    assert outcome.status == "open"
    steps = [e for e in recorder.events if e in ("tier1", "review", "verify_base", "push")]
    assert steps == ["tier1", "review", "verify_base", "tier1", "push"]
    assert recorder.remote == ["sha-3"], "the moved head, not the one review saw"
    assert recorder.store.get(unit().id).approved == "sha-3"


# --- rework, replies and tier 1 for a unit with nothing ---------------------------


def test_a_rework_of_an_open_pr_posts_its_replies_after_the_push(tmp_path: Path) -> None:
    """After, so a reply describes code the reviewer can already see."""
    recorder = fresh(tmp_path)
    recorder.store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))
    recorder.store.set_feedback(unit().id, "[comment 11] a.py:3 — rename", from_person=True)
    replies: list[dict] = []

    def reply(**kwargs: Any) -> None:
        recorder.events.append("reply")
        replies.append(kwargs)

    build(tmp_path, recorder, reply=reply)

    assert recorder.events.index("reply") > recorder.events.index("push")
    assert replies[0]["pr"] == 7 and replies[0]["answer_text"] == "done"
    assert recorder.store.get(unit().id).pending_replies == (), "cleared once posted"


def test_a_review_after_a_persons_comments_in_the_graph_is_given_them_and_they_clear_on_push(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))
    recorder.store.set_feedback(unit().id, "[comment 11] a.py:3 — rename", from_person=True)

    build(tmp_path, recorder)

    assert "> [comment 11] a.py:3 — rename" in recorder.contexts[0]
    assert recorder.store.get(unit().id).person_comments == ""


def test_a_first_build_has_nobody_to_reply_to(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    replies: list[dict] = []

    build(tmp_path, recorder, reply=lambda **kwargs: replies.append(kwargs))

    assert replies == []


def test_a_unit_with_nothing_anywhere_still_fails(tmp_path: Path) -> None:
    """No commits of its own is not enough to call a unit satisfied: the checks
    have to pass too."""
    recorder = fresh(tmp_path, commits_from_impl=0, tier1_ok=False)

    outcome = build(tmp_path, recorder, branch_commits=lambda cwd, base: 0)

    assert outcome.status == "failed"
    assert "tier 1 failed" in outcome.detail
    assert "tier1:whole_repo" in recorder.events, (
        "judged on the whole-repo checks, not skipped because nothing landed"
    )


def test_a_unit_retried_after_tier_one_takes_the_rework_path(tmp_path: Path) -> None:
    """One scoped run against the recorded failure, not the tests-then-
    implementation pair against a branch that already has both."""
    recorder = fresh(tmp_path)
    recorder.store.set_feedback(unit().id, "tier 1 failed:\nE   ImportError: no module named x")

    build(tmp_path, recorder)

    assert len(recorder.prompts) == 1
    assert "ImportError" in recorder.prompts[0]
    assert recorder.events.count("claude:fix_checks") == 1, "the checks prompt"


def test_rework_runs_on_the_review_model(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.store.set_feedback(unit().id, "make it a StrEnum")
    used: list[str] = []

    build(tmp_path, recorder, run_rework=lambda prompt, **k: used.append("rework-model") or "")

    assert used == ["rework-model"], "rework goes through its own call, not run_claude"
    assert recorder.prompts == []
