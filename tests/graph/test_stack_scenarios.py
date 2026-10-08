"""What a unit's prompts say, what the review loop is told, and what the build
leaves behind, run through the graph engine over the injected fakes.

These are the scenarios of the engine the graph replaced that its nodes still
owe: the boundary every agent run is given, the history a later review sees,
the order tasks are ticked in, the base a unit is built on, and what a unit
that touches only tier 1 does not do.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.units import IN_REVIEW, branch_name
from tests.factories import activate_with, stored_unit, unit
from tests.graph.test_build_path import build, restacked
from tests.graph.test_remaining_paths import fresh, tasks_file
from tests.runner_fakes import Recorder, approving, rejecting

LATER = [
    stored_unit("add-marker/1", groups=(1,)),
    stored_unit("add-marker/2", groups=(2, 3), depends_on=("add-marker/1",)),
]
ALONE = [stored_unit("add-marker/1", groups=(1,))]


def rework_prompts(recorder: Recorder) -> list[str]:
    return [p for p in recorder.prompts if "review of this branch" in p.lower()]


# --- the boundary --------------------------------------------------------------


def test_the_tests_prompt_asks_for_failing_tests_and_no_logic(tmp_path: Path) -> None:
    """The prompt is what makes the commit-order hook pass rather than fire."""
    recorder = fresh(tmp_path)

    build(tmp_path, recorder)

    tests_prompt = recorder.prompts[0]
    assert "test tasks" in tests_prompt
    assert "fail" in tests_prompt
    assert "NotImplementedError" in tests_prompt


def test_the_build_prompts_name_the_later_units_boundary_and_why(tmp_path: Path) -> None:
    """The builder can see the whole of tasks.md, so leaving the groups after
    its own alone has to be said, with its reason."""
    recorder = fresh(tmp_path)

    build(tmp_path, recorder, graph=LATER)

    assert len(recorder.prompts) == 2, "both the tests and the implementation prompts ran"
    for prompt in recorder.prompts:
        assert "2, 3" in prompt, "the later unit's groups are named, not just this one's own"
        assert "later" in prompt.lower(), "named as belonging to a later unit"
        assert "pull request" in prompt.lower(), "the boundary is given with its reason"


def test_the_review_is_told_the_same_boundary(tmp_path: Path) -> None:
    """A finding whose fix belongs to a later group is reported as belonging
    there, not required of this unit."""
    recorder = fresh(tmp_path)

    build(tmp_path, recorder, graph=LATER)

    assert any(
        "2, 3" in context and "later" in context.lower() and "belong" in context.lower()
        for context in recorder.contexts
    ), "the reviewer is told which groups are not this unit's to require"


def test_the_rework_prompt_carries_the_same_boundary_as_the_build(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("consider handling group 2's case too"), approving()]

    build(tmp_path, recorder, graph=LATER)

    prompts = rework_prompts(recorder)
    assert prompts, "the rework prompt ran"
    assert "2, 3" in prompts[0], "the later unit's groups are named"
    assert "leave" in prompts[0].lower(), "and left alone, not implemented"


def test_no_boundary_is_given_when_there_is_no_later_unit(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("rename it"), approving()]

    build(tmp_path, recorder, graph=ALONE)

    assert rework_prompts(recorder), "the rework prompt ran too"
    for prompt in recorder.prompts:
        assert "belong" not in prompt.lower()
    for context in recorder.contexts:
        assert "belong" not in context.lower()


def test_the_rework_prompt_allows_pushing_back_and_names_the_pull_request(tmp_path: Path) -> None:
    """A reviewer can be wrong in a way the code cannot be."""
    recorder = fresh(tmp_path)
    recorder.store.set_state(unit().id, IN_REVIEW, pr=16, branch=branch_name(unit()))
    recorder.store.set_feedback(unit().id, "make it a StrEnum")
    prompts: list[str] = []

    def rework(prompt: str, **session: Any) -> str:
        prompts.append(prompt)
        return ""

    build(tmp_path, recorder, run=rework)

    assert "16" in prompts[0], "it needs the PR number to reply on"
    lowered = prompts[0].lower()
    assert "what was **meant**" in lowered or "intent" in lowered
    assert "comment" in lowered


# --- what a later review is told ------------------------------------------------


def test_a_later_review_sees_what_earlier_rounds_asked_and_what_was_done(
    tmp_path: Path,
) -> None:
    """Without it each round starts over: reviews find new, neighbouring
    problems every round, with no way to check the last ones were met."""
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("fill times out on long text"), approving()]

    def run(prompt: str, **session: Any) -> str:
        answer = recorder.claude(prompt, **session)
        return (
            "Scaled the timeout with text length."
            if recorder.events[-1] == "claude:rework"
            else answer
        )

    build(tmp_path, recorder, run=run)

    assert "The builder's response" not in recorder.contexts[0], "the first review has no history"
    later = recorder.contexts[1]
    assert "round 2 of the loop" in later
    assert "fill times out on long text" in later
    assert "Scaled the timeout with text length." in later
    assert "Do not re-open points that are settled" in later


# --- ticking tasks --------------------------------------------------------------


def test_tasks_are_ticked_when_the_unit_is_through_the_loop_not_before(tmp_path: Path) -> None:
    """Ticked once review approved, tier 1 passed and the work is pushed, never
    by a build that has merely finished."""
    tasks = tasks_file(tmp_path)
    recorder = fresh(tmp_path)
    seen_at_review: list[str] = []

    def review(*, cwd: Path, context: str = "", **session: Any) -> str:
        seen_at_review.append(tasks.read_text())
        return recorder.review(cwd=cwd, context=context)

    build(tmp_path, recorder, run_review=review, run_rework_review=review)

    assert seen_at_review and "- [ ]" in seen_at_review[0], "not yet ticked while under review"
    assert "- [x]" not in seen_at_review[0]
    assert tasks.read_text().count("- [x]") == 2


def test_a_failed_unit_leaves_its_tasks_unticked(tmp_path: Path) -> None:
    tasks = tasks_file(tmp_path)
    tasks.write_text(tasks.read_text().replace("- [ ]", "- [x]"))  # a build agent's doing
    recorder = fresh(tmp_path, tier1_ok=False)

    outcome = build(tmp_path, recorder)

    assert outcome.status == "failed"
    assert "- [x]" not in tasks.read_text()


# --- where the work is built and what the tiers touch ---------------------------


def test_work_is_built_on_the_remote_trunk_but_the_pr_targets_main(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    worktree_bases: list[str] = []
    pr_bases: list[str] = []

    def worktree(u: Any, base: str) -> Path:
        worktree_bases.append(base)
        return tmp_path / "tree"

    def open_pr(u: Any, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
        pr_bases.append(base)
        return recorder.open_pr(u, body=body, base=base, cwd=cwd)

    build(tmp_path, recorder, worktree=worktree, open_pr=open_pr)

    assert worktree_bases and set(worktree_bases) == {"origin/main"}
    assert pr_bases == ["main"]


def test_a_tier_one_unit_does_not_touch_the_local_stack(tmp_path: Path) -> None:
    """Tier 2 is serialized, so running it needlessly would block other work."""
    recorder = fresh(tmp_path)

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    assert "tier2" not in recorder.events
    assert "status" not in recorder.events


def test_a_finished_unit_opens_its_pull_request_at_the_limit(tmp_path: Path) -> None:
    """The limit gates starting, never finishing: reviewed work is pushed and
    its pull request opened even when the units in progress are at the limit."""
    activate_with(limits=dict(max_units_in_progress=1))
    recorder = fresh(tmp_path)
    others = [
        stored_unit(f"other-{n}/1", change=f"other-{n}", state=IN_REVIEW, pr=20 + n)
        for n in range(3)
    ]
    recorder.store.upsert(others)

    outcome = build(tmp_path, recorder, graph=[*others, recorder.store.get(unit().id)])

    assert outcome.status == "open"
    assert "push" in recorder.events and "pr" in recorder.events
    assert recorder.store.get(unit().id).state == IN_REVIEW


def test_a_branch_with_nothing_on_it_is_not_reviewed(tmp_path: Path) -> None:
    """Reviewing an empty branch spends a model call to say nothing."""
    recorder = fresh(tmp_path, commits_from_impl=0)

    build(tmp_path, recorder, branch_commits=lambda cwd, base: 0)

    assert "review" not in recorder.events


def test_nothing_is_pushed_but_the_commit_review_approved(tmp_path: Path) -> None:
    """A commit landing after the verdict, here tier 2 making one, fails the
    unit instead of reaching the pull request."""
    recorder = fresh(tmp_path, tier="tier2")
    original = recorder.tier2

    def tier2_that_commits(*, cwd: Path) -> tuple[bool, str]:
        recorder.made += 1
        return original(cwd=cwd)

    outcome = build(tmp_path, recorder, run_tier2=tier2_that_commits)

    assert outcome.status == "failed"
    assert "push" not in recorder.events


def test_a_commit_tier_one_makes_before_the_review_is_the_commit_that_is_reviewed(
    tmp_path: Path,
) -> None:
    """An autoformatter in a check can rewrite files; run before the review,
    that is just more of the branch the reviewer reads and approves."""
    recorder = fresh(tmp_path)
    original = recorder.tier1

    def tier1_that_commits(
        *, cwd: Path, base: str = "main", whole_repo: bool = False
    ) -> tuple[bool, str]:
        recorder.made += 1
        return original(cwd=cwd, base=base, whole_repo=whole_repo)

    outcome = build(tmp_path, recorder, run_tier1=tier1_that_commits)

    assert outcome.status == "open"
    assert recorder.store.get(unit().id).approved == recorder.head(tmp_path)


# --- the checks' output reaches the run log ---------------------------------------


def test_a_failed_tier_ones_output_reaches_the_run_log(tmp_path: Path) -> None:
    """The run log is what a person reads to see why a unit failed."""
    recorder = fresh(tmp_path, tier1_ok=False)
    recorder.tier1_output = "E   DISTINCTIVE-TIER-ONE-OUTPUT"

    build(tmp_path, recorder)

    assert any("E   DISTINCTIVE-TIER-ONE-OUTPUT" in line for line in recorder.logged)


def test_a_tier_one_that_fails_after_a_clean_move_logs_its_output(tmp_path: Path) -> None:
    """The re-check before the push, on the base as it now is, is a tier 1 too."""
    recorder = fresh(tmp_path)
    recorder.made = 2
    recorder.tier1_results = [(True, ""), (False, "E   DISTINCTIVE-RECHECK-OUTPUT")]
    calls: list[int] = []

    def restack(**kw: Any) -> Any:
        calls.append(1)
        return restacked() if len(calls) == 2 else None

    build(tmp_path, recorder, restack_onto=restack)

    assert any("E   DISTINCTIVE-RECHECK-OUTPUT" in line for line in recorder.logged)


# --- who commits ------------------------------------------------------------------


class SelfCommitting(Recorder):
    """An agent that commits its own work, leaving the pipeline nothing."""

    def claude(self, prompt: str, *, cwd: Path, **session: Any) -> str:
        self.made += 1
        return super().claude(prompt, cwd=cwd, **session)

    def commit(self, message: str, *, cwd: Path) -> int:
        self.events.append(f"commit:{message.split(':')[0]}")
        return 0


def self_committing(tmp_path: Path) -> SelfCommitting:
    plain = fresh(tmp_path)
    return SelfCommitting(plain.store)


def test_a_build_the_agent_committed_itself_is_still_reviewed(tmp_path: Path) -> None:
    """Read from the commit step, it looked like the run produced nothing."""
    recorder = self_committing(tmp_path)

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    assert "review" in recorder.events


def test_a_rework_is_always_reviewed(tmp_path: Path) -> None:
    """When the rework agent commits its change itself, the branch, carrying
    rounds its review had rejected, would otherwise reach the pull request
    with no review at all."""
    recorder = self_committing(tmp_path)
    recorder.store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))
    recorder.store.set_feedback(unit().id, "rename it")
    recorder.made = 2

    build(tmp_path, recorder)

    assert recorder.events.index("review") < recorder.events.index("push")


def test_a_rework_is_judged_by_the_rework_reviewer(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))
    recorder.store.set_feedback(unit().id, "rename it")
    recorder.made = 2
    used: list[str] = []

    def named(name: str) -> Any:
        def review(**kwargs: Any) -> str:
            used.append(name)
            return recorder.review(**kwargs)

        return review

    build(tmp_path, recorder, run_review=named("standard"), run_rework_review=named("rework"))

    assert used == ["rework"]


def test_a_reviewer_that_never_approves_is_asked_once_per_round_and_no_rework_follows(
    tmp_path: Path,
) -> None:
    """After the last review nothing would review a rework: the unit goes to a
    person either way, having paid for a rework nobody sees."""
    recorder = fresh(tmp_path)
    recorder.verdicts = [json.dumps({"approved": False, "feedback": "no"})] * 3

    outcome = build(tmp_path, recorder)

    assert outcome.status == "held"
    assert recorder.events.count("review") == 3
    assert recorder.events.count("claude:rework") == 2
