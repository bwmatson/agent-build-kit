"""Driving one unit from planned to open PR.

This is where every other piece is finally sequenced, and the sequence *is*
the guarantee. Almost all of these tests are about order and refusal rather
than output:

- nothing starts when the usage window is low,
- tests are written and committed before any implementation,
- the review pass only runs if there was something to review,
- tier 2 passes before anything is pushed,
- the commit status is posted after the push, never before,
- and a failure anywhere leaves no PR behind.

Side effects are injected, so these run in milliseconds and assert the shape
of the run rather than shelling out to Claude, git and gh.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.pipeline.diagram import render_mermaid
from agent_build_kit.pipeline.restack import HostMoved
from agent_build_kit.pipeline.stack_runner import IMPLEMENT, REWORK, Restacked, UnitRunner
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, branch_name, waiting_on
from agent_build_kit.pipeline.usage_guard import Interrupted, RateLimited
from tests.factories import stored_unit, unit


class Recorder:
    """Stands in for every side effect, recording what happened in order."""

    tier1_output: str = ""

    def __init__(
        self,
        *,
        commits_from_impl: int = 1,
        tier2_ok: bool = True,
        tier1_ok: bool = True,
        close_error: str = "",
    ):
        self.events: list[str] = []
        self.prompts: list[str] = []
        self.commits_from_impl = commits_from_impl
        self.tier2_ok = tier2_ok
        self.tier1_ok = tier1_ok
        self.pushed_shas: list[str] = []
        self.close_error = close_error
        self.closed: list[tuple[str, int, str]] = []
        self.logged: list[str] = []

    def claude(self, prompt: str, *, cwd: Path) -> str:
        self.prompts.append(prompt)
        if "Review asked for" in prompt or "review of this branch" in prompt:
            self.events.append("claude:rework")
        else:
            self.events.append("claude:tests" if "test tasks" in prompt else "claude:impl")
        return "done"

    verdicts: list[str] = []

    contexts: list[str]

    def review(self, *, cwd: Path, context: str = "") -> str:
        """Takes `context` as the real review does: a fake that did not hid
        that the real one did not, and a review crashed in the field."""
        self.contexts = [*getattr(self, "contexts", []), context]
        self.events.append("review")
        return self.verdicts.pop(0) if self.verdicts else '{"approved": true, "feedback": ""}'

    made: int = 0

    def commit(self, message: str, *, cwd: Path) -> int:
        self.events.append(f"commit:{message.split(':')[0]}")
        count = 1 if "test" in message else self.commits_from_impl
        self.made += count
        return count

    def branch_commits(self, cwd: Path, base: str) -> int:
        """What is on the branch: every commit made so far."""
        return self.made

    def head(self, cwd: Path) -> str:
        """Moves with every commit, as a real HEAD does."""
        return f"sha-{self.made}"

    def tier1(self, *, cwd: Path, base: str = "main", whole_repo: bool = False) -> tuple[bool, str]:
        self.events.append("tier1:whole_repo" if whole_repo else "tier1")
        return self.tier1_ok, self.tier1_output

    def tier2(self, *, cwd: Path) -> tuple[bool, str]:
        self.events.append("tier2")
        return self.tier2_ok, "## Tier 2 results\nfine"

    def push(self, branch: str, *, cwd: Path) -> str:
        self.events.append("push")
        self.pushed_shas.append("abc123")
        return "abc123"

    def open_pr(self, unit, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
        self.events.append("pr")
        return 7

    def post_status(self, sha: str, ok: bool) -> None:
        self.events.append("status")

    def close_pr(self, unit, pr: int, reason: str) -> None:
        self.events.append("close")
        if self.close_error:
            raise RuntimeError(self.close_error)
        self.closed.append((unit.id, pr, reason))

    def log(self, message: str) -> None:
        self.logged.append(message)


@pytest.fixture
def runner(tmp_path: Path):
    def build(recorder: Recorder, *, may_start: bool = True, tier: str = "tier1") -> UnitRunner:
        store = UnitStore(tmp_path / "units.json")
        store.upsert([unit(tier=tier)])
        return UnitRunner(
            store=store,
            planning_repo=tmp_path / "meta",
            worktree=lambda u, base: tmp_path / "tree",
            may_start=lambda: (may_start, "usage fine" if may_start else "session at 88%"),
            run_claude=recorder.claude,
            run_rework=recorder.claude,
            run_review=recorder.review,
            run_rework_review=recorder.review,
            commit=recorder.commit,
            branch_commits=recorder.branch_commits,
            head=recorder.head,
            upstream_incomplete=lambda u: "",
            restack_onto=lambda **kw: None,
            run_tier1=recorder.tier1,
            run_tier2=recorder.tier2,
            push=recorder.push,
            open_pr=recorder.open_pr,
            post_status=recorder.post_status,
            close_pr=recorder.close_pr,
            log=recorder.log,
        )

    return build


def test_a_unit_runs_tests_first_then_implementation(runner) -> None:
    recorder = Recorder()

    runner(recorder).run(unit(), base="main", graph=[])

    assert recorder.events[:4] == ["claude:tests", "commit:test", "claude:impl", "commit:feat"]


def test_the_tests_prompt_asks_for_failing_tests_and_no_logic(runner) -> None:
    """The prompt is what makes the commit-order hook pass rather than fire."""
    recorder = Recorder()

    runner(recorder).run(unit(), base="main", graph=[])

    tests_prompt = recorder.prompts[0]
    assert "test tasks" in tests_prompt
    assert "fail" in tests_prompt
    assert "NotImplementedError" in tests_prompt


def test_each_run_is_scoped_to_this_unit_only(runner) -> None:
    """One unit per run: a wider scope drains the backlog onto one branch and
    defeats the per-unit review."""
    recorder = Recorder()

    runner(recorder).run(unit(groups=(2, 3)), base="main", graph=[])

    assert all("2, 3" in prompt for prompt in recorder.prompts)
    assert all("add-marker" in prompt for prompt in recorder.prompts)


def test_the_build_prompts_name_the_boundary_and_why(runner) -> None:
    """The builder can see the whole of tasks.md, including the groups after
    its own — so leaving them alone has to be said, not left to be inferred,
    or a capable agent finishes the group after it too because the code for
    it is already sitting right there."""
    recorder = Recorder()
    graph = [
        stored_unit("add-marker/1", groups=(1,)),
        stored_unit("add-marker/2", groups=(2, 3), depends_on=("add-marker/1",)),
    ]

    runner(recorder).run(unit(groups=(1,)), base="main", graph=graph)

    assert len(recorder.prompts) >= 2, "both the tests and the implementation prompts ran"
    for prompt in recorder.prompts[:2]:
        assert "2, 3" in prompt, "the later unit's groups are named, not just this one's own"
        assert "later" in prompt.lower(), "named as belonging to a later unit"
        assert "pull request" in prompt.lower(), "the boundary is given with its reason"


def test_the_review_is_told_the_same_boundary(runner) -> None:
    """A finding whose fix belongs to a later group is reported as belonging
    there, not required of this unit — so the reviewer needs the same
    boundary the builder was given, and keeps its full reach over the rest."""
    from agent_build_kit.pipeline.wiring import REVIEW_PROMPT

    recorder = Recorder()
    graph = [
        stored_unit("add-marker/1", groups=(1,)),
        stored_unit("add-marker/2", groups=(2, 3), depends_on=("add-marker/1",)),
    ]

    runner(recorder).run(unit(groups=(1,)), base="main", graph=graph)

    assert any(
        "2, 3" in context and "later" in context.lower() and "belong" in context.lower()
        for context in recorder.contexts
    ), "the reviewer is told which groups are not this unit's to require"
    # its reach over the unit's own groups keeps its current force
    assert "Find everything in one pass" in REVIEW_PROMPT
    assert "Sweep the domain" in REVIEW_PROMPT


def test_no_boundary_is_given_when_there_is_no_later_unit(runner) -> None:
    """A change with only this unit left has nothing to protect a boundary
    from — naming an empty later group would just be noise in every prompt."""
    recorder = Recorder()
    graph = [stored_unit("add-marker/1", groups=(1,))]

    runner(recorder).run(unit(groups=(1,)), base="main", graph=graph)

    for prompt in recorder.prompts:
        assert "belong" not in prompt.lower()
    for context in getattr(recorder, "contexts", []):
        assert "belong" not in context.lower()


def test_nothing_happens_when_the_usage_window_is_low(runner) -> None:
    """The guard gates starting work, so the refusal must come before the
    worktree, not after the first expensive call."""
    recorder = Recorder()

    outcome = runner(recorder, may_start=False).run(unit(), base="main", graph=[])

    assert outcome.status == "paused"
    assert recorder.events == []
    assert "88%" in outcome.detail


def test_the_review_pass_runs_only_when_there_were_commits(runner) -> None:
    """Reviewing an empty branch spends a model call to say nothing."""
    recorder = Recorder(commits_from_impl=0)
    built = runner(recorder)
    built.branch_commits = lambda cwd, base: 0  # nothing landed anywhere, ever

    built.run(unit(), base="main", graph=[])

    assert "review" not in recorder.events


def test_a_unit_whose_remaining_work_is_already_implemented_still_goes_to_review(
    runner,
) -> None:
    """The implementation step adding nothing is not the same as the unit
    adding nothing: its tests commit is this unit's own work, so there is a
    diff on the branch, and a diff is reviewed rather than treated as empty."""
    recorder = Recorder(commits_from_impl=0)

    outcome = runner(recorder).run(unit(), base="main", graph=[])

    assert "review" in recorder.events
    assert outcome.status == "open"


def test_the_review_pass_runs_before_the_tests_do(runner) -> None:
    """Cheap first: a review that rewrites code would invalidate a test run
    done before it."""
    recorder = Recorder()

    runner(recorder).run(unit(), base="main", graph=[])

    assert recorder.events.index("review") < recorder.events.index("tier1")


def test_tier_two_runs_before_the_push_for_a_tier_two_unit(runner) -> None:
    recorder = Recorder()

    runner(recorder, tier="tier2").run(unit(tier="tier2"), base="main", graph=[])

    assert recorder.events.index("tier2") < recorder.events.index("push")


def test_a_tier_one_unit_does_not_touch_the_local_stack(runner) -> None:
    """Tier 2 is serialized, so running it needlessly would block other work."""
    recorder = Recorder()

    runner(recorder).run(unit(), base="main", graph=[])

    assert "tier2" not in recorder.events


def test_a_failing_tier_two_leaves_no_pr_behind(runner) -> None:
    """Tier 2 gates the push: nothing is pushed, so there is nothing to
    attach a snapshot or a status to."""
    recorder = Recorder(tier2_ok=False)

    outcome = runner(recorder, tier="tier2").run(unit(tier="tier2"), base="main", graph=[])

    assert outcome.status == "failed"
    assert "push" not in recorder.events
    assert "pr" not in recorder.events


def test_a_failing_tier_one_stops_before_tier_two(runner) -> None:
    """No point occupying the one local stack to re-confirm a known failure."""
    recorder = Recorder(tier1_ok=False)

    runner(recorder, tier="tier2").run(unit(tier="tier2"), base="main", graph=[])

    assert "tier2" not in recorder.events
    assert "push" not in recorder.events


def test_the_status_is_posted_after_the_push(runner) -> None:
    """GitHub only accepts a status for a commit it already has."""
    recorder = Recorder()

    runner(recorder, tier="tier2").run(unit(tier="tier2"), base="main", graph=[])

    assert recorder.events.index("push") < recorder.events.index("status")


def test_a_successful_run_records_the_unit_as_open(runner, tmp_path: Path) -> None:
    recorder = Recorder()
    unit_runner = runner(recorder)

    unit_runner.run(unit(), base="main", graph=[])

    stored = unit_runner.store.get("add-marker/1")
    assert stored.state == "in_review"
    assert stored.pr == 7
    assert stored.branch == "spec/add-marker/1"


def test_a_failed_run_is_recorded_rather_than_left_looking_planned(runner) -> None:
    """A unit stuck at "planned" would be picked up again next round and redo
    the same failing work."""
    recorder = Recorder(tier1_ok=False)
    unit_runner = runner(recorder)

    unit_runner.run(unit(), base="main", graph=[])

    assert unit_runner.store.get("add-marker/1").state == "failed"


def make_runner(store: UnitStore, recorder: Recorder, tmp_path: Path) -> UnitRunner:
    return UnitRunner(
        store=store,
        planning_repo=tmp_path / "meta",
        worktree=lambda u, base: tmp_path / "tree",
        may_start=lambda: (True, "usage fine"),
        run_claude=recorder.claude,
        run_rework=recorder.claude,
        run_review=recorder.review,
        run_rework_review=recorder.review,
        commit=recorder.commit,
        branch_commits=recorder.branch_commits,
        head=recorder.head,
        upstream_incomplete=lambda u: "",
        restack_onto=lambda **kw: None,
        run_tier1=recorder.tier1,
        run_tier2=recorder.tier2,
        push=recorder.push,
        open_pr=recorder.open_pr,
        post_status=recorder.post_status,
        close_pr=recorder.close_pr,
        log=recorder.log,
    )


def test_a_reworked_unit_addresses_the_feedback_instead_of_starting_over(tmp_path: Path) -> None:
    """Its tests and implementation already exist. Re-running the tests step
    would write tests that are already there, and the implementation prompt
    knows nothing about what the reviewer objected to."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))
    store.set_feedback(unit().id, "Use a Sequence, list is invariant")
    recorder = Recorder()

    make_runner(store, recorder, tmp_path).run(store.get(unit().id), base="main", graph=[])

    assert len(recorder.prompts) == 1, "one run, not the usual tests-then-implementation pair"
    assert "Use a Sequence, list is invariant" in recorder.prompts[0]


def test_the_feedback_is_cleared_once_it_has_been_addressed(tmp_path: Path) -> None:
    """Left in place, the next tick would rework the unit again for a comment
    it has already answered — forever."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))
    store.set_feedback(unit().id, "Use a Sequence")

    make_runner(store, Recorder(), tmp_path).run(store.get(unit().id), base="main", graph=[])

    assert store.get(unit().id).feedback == ""


def test_a_fresh_unit_still_gets_the_two_step_run(tmp_path: Path) -> None:
    """The tests commit is the only evidence the tests ever failed, so a unit
    with no feedback must not take the rework shortcut."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()

    make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert len(recorder.prompts) == 2


def test_the_prompts_name_the_change_rather_than_a_slash_command(tmp_path: Path) -> None:
    """`/opsx:apply` only exists where OpenSpec is installed — the planning
    repo — and the unit is built in the target repo's worktree. The first
    pilot run got "Unknown command: /opsx:apply" and wrote nothing."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()

    make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    for prompt in recorder.prompts:
        assert "/opsx:" not in prompt
        assert "openspec/changes/add-marker" in prompt


def test_a_unit_resumes_from_work_already_on_its_branch(tmp_path: Path) -> None:
    """Both pilot units failed at tier 1 *after* committing correct work. If a
    re-run means "did this run produce commits", the answer is no and the unit
    fails again — so work that exists and is good can never be retried."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder(commits_from_impl=0)
    runner = make_runner(store, recorder, tmp_path)
    runner.branch_commits = lambda cwd, base: 2  # the tests and feat commits

    outcome = runner.run(unit(), base="main", graph=[])

    assert outcome.status == "open"
    assert "tier1" in recorder.events, "it goes on to verify what is there"


def test_a_unit_with_nothing_anywhere_still_fails(tmp_path: Path) -> None:
    """No commits of its own is not enough by itself to call a unit
    satisfied — the checks have to pass too, or this is a real failure, not
    work that arrived another way."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder(commits_from_impl=0, tier1_ok=False)
    runner = make_runner(store, recorder, tmp_path)
    runner.branch_commits = lambda cwd, base: 0

    outcome = runner.run(unit(), base="main", graph=[])

    assert outcome.status == "failed"
    assert "tier1:whole_repo" in recorder.events, (
        "judged on the whole-repo checks, not skipped because nothing landed"
    )


def test_a_unit_with_nothing_of_its_own_and_passing_checks_is_satisfied(tmp_path: Path) -> None:
    """A predecessor did the work: nothing for this unit to add, and what is
    already there passes. That is not a failure — it is satisfied, judged
    from the branch and the checks, never from anything the run says about
    itself."""
    tasks = _tasks_file(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder(commits_from_impl=0, tier1_ok=True)
    runner = make_runner(store, recorder, tmp_path)
    runner.branch_commits = lambda cwd, base: 0

    outcome = runner.run(unit(), base="main", graph=[])

    assert outcome.status == "satisfied"
    assert "tier1:whole_repo" in recorder.events, (
        "judged on the whole-repo checks, not the run's own report"
    )
    assert "pr" not in recorder.events, "nothing to open a pull request for"
    assert "push" not in recorder.events, "nothing to push either"
    assert "close" not in recorder.events, "there was never a pull request to close either"
    assert store.get(unit().id).state == "satisfied"
    assert tasks.read_text().count("- [x]") == 2, "its groups are ticked all the same"

    dependent = unit(uid="add-marker/2", depends_on=(unit().id,))
    assert waiting_on(dependent, [store.get(unit().id)]) == [], "dependents stop waiting for it"


def test_a_satisfied_unit_posts_the_reason_before_closing_its_open_pull_request(
    tmp_path: Path,
) -> None:
    """A rework that finds the work has landed elsewhere in the meantime — the
    restack having dropped its commits as empty because the predecessor now
    carries the same change — leaves an open pull request with no diff and no
    future. The explanation must never be missing, so it is posted before the
    close is even attempted — one call does both, in that order.

    Reached from feedback waiting on an open PR, the real path: nothing here
    goes through the tests or implementation prompts at all."""
    _tasks_file(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))
    store.set_feedback(unit().id, "please double-check the edge case")
    store.set_pending_replies(unit().id, ("done",))
    recorder = Recorder(commits_from_impl=0, tier1_ok=True)
    runner = make_runner(store, recorder, tmp_path)
    runner.branch_commits = lambda cwd, base: 0

    outcome = runner.run(unit(), base="main", graph=[store.get(unit().id)])

    assert outcome.status == "satisfied"
    assert store.get(unit().id).feedback == "", "a satisfied unit carries no review feedback"
    assert store.get(unit().id).pending_replies == (), "nor replies to a review it no longer has"
    assert recorder.events.count("claude:rework") == 1
    assert "claude:tests" not in recorder.events
    assert "claude:impl" not in recorder.events
    assert "review" not in recorder.events
    assert recorder.events.count("close") == 1
    (unit_id, pr, reason) = recorder.closed[0]
    assert unit_id == unit().id
    assert pr == 4
    assert "Task group(s) 1" in reason and "implemented elsewhere" in reason.lower()


def test_a_satisfied_unit_resuming_before_its_rework_is_also_reached(tmp_path: Path) -> None:
    """The same empty-branch-after-restack outcome, reached from a unit that
    stopped between a review and its rework rather than one freshly picked up
    with feedback waiting."""
    _tasks_file(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()), resume_from=REWORK)
    store.set_feedback(unit().id, "please double-check the edge case")
    store.set_pending_replies(unit().id, ("done",))
    recorder = Recorder(commits_from_impl=0, tier1_ok=True)
    runner = make_runner(store, recorder, tmp_path)
    runner.branch_commits = lambda cwd, base: 0

    outcome = runner.run(unit(), base="main", graph=[store.get(unit().id)])

    assert outcome.status == "satisfied"
    assert store.get(unit().id).feedback == ""
    assert store.get(unit().id).pending_replies == ()
    assert recorder.events.count("claude:rework") == 1
    assert recorder.events.count("close") == 1
    assert recorder.closed[0][1] == 4


def test_a_satisfied_unit_with_no_pull_request_posts_and_closes_nothing(tmp_path: Path) -> None:
    _tasks_file(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder(commits_from_impl=0, tier1_ok=True)
    runner = make_runner(store, recorder, tmp_path)
    runner.branch_commits = lambda cwd, base: 0

    runner.run(unit(), base="main", graph=[])

    assert "close" not in recorder.events


def test_a_failure_to_close_a_satisfied_units_pull_request_is_recorded_and_leaves_it_satisfied(
    tmp_path: Path,
) -> None:
    """The judgement rests on the branch and the checks; a stale pull request
    that refuses to close is a nuisance, not a reason to revisit it."""
    _tasks_file(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))
    recorder = Recorder(commits_from_impl=0, tier1_ok=True, close_error="404 gone")
    runner = make_runner(store, recorder, tmp_path)
    runner.branch_commits = lambda cwd, base: 0

    outcome = runner.run(unit(), base="main", graph=[store.get(unit().id)])

    assert outcome.status == "satisfied"
    assert store.get(unit().id).state == "satisfied"
    assert any("404 gone" in message for message in recorder.logged)
    note = store.get(unit().id).history[-1]["note"]
    assert "404 gone" in note


def test_no_model_call_decides_or_writes_the_satisfied_close(tmp_path: Path) -> None:
    """The judgement that gets a unit here (no commits of its own, tier 1
    green) is already mechanical, and so is the text posted on its pull
    request — nothing after the checks may ask an agent anything."""
    _tasks_file(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))
    store.set_feedback(unit().id, "please double-check the edge case")
    recorder = Recorder(commits_from_impl=0, tier1_ok=True)
    runner = make_runner(store, recorder, tmp_path)
    runner.branch_commits = lambda cwd, base: 0

    runner.run(unit(), base="main", graph=[store.get(unit().id)])

    assert "review" not in recorder.events, "no review round runs for an empty branch"
    after_checks = recorder.events[recorder.events.index("tier1:whole_repo") + 1 :]
    assert not any(event.startswith("claude") or event == "review" for event in after_checks), (
        "nothing asks an agent anything once the checks have judged the branch"
    )


def test_a_resumed_unit_is_not_reviewed_again_at_the_commit_it_approved(tmp_path: Path) -> None:
    """Nothing was written since, and review approved exactly this commit."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder(commits_from_impl=0)
    store.record_approval(unit().id, recorder.head(tmp_path))
    runner = make_runner(store, recorder, tmp_path)
    runner.branch_commits = lambda cwd, base: 2

    runner.run(unit(), base="main", graph=[])

    assert "review" not in recorder.events
    assert "push" in recorder.events


def test_a_branch_review_never_approved_is_reviewed_before_it_is_pushed(tmp_path: Path) -> None:
    """The "branch already has this unit's work" path used to push without a
    review, on the assumption that it had been reviewed when it was written."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder(commits_from_impl=0)
    runner = make_runner(store, recorder, tmp_path)
    runner.branch_commits = lambda cwd, base: 2

    runner.run(unit(), base="main", graph=[])

    assert recorder.events.index("review") < recorder.events.index("push")


def test_nothing_is_pushed_but_the_commit_review_approved(tmp_path: Path) -> None:
    """The rule, checked at the push: a commit landing after the verdict —
    here tier 1 making one — fails the unit instead of reaching the PR."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    original_tier1 = recorder.tier1

    def tier1_that_commits(
        *, cwd: Path, base: str = "main", whole_repo: bool = False
    ) -> tuple[bool, str]:
        recorder.made += 1
        return original_tier1(cwd=cwd, base=base, whole_repo=whole_repo)

    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={"run_tier1": tier1_that_commits}
    )
    outcome = runner.run(unit(), base="main", graph=[])

    assert outcome.status == "failed"
    assert "push" not in recorder.events


def test_the_review_pass_s_work_is_committed(tmp_path: Path) -> None:
    """It was not, and the pilot showed what that costs: the review added a
    test-tiers section to platform's CLAUDE.md, the runner never committed
    it, and the next run refused to start because the worktree was dirty. The
    tidy-up is either part of the unit or it is litter that blocks the retry."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()

    make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert recorder.events.index("review") < recorder.events.index("tier1")
    before_review = recorder.events[recorder.events.index("review") - 1]
    assert before_review.startswith("commit:"), "the tree is committed before review looks"


def test_the_branch_ends_with_exactly_three_commit_attempts(tmp_path: Path) -> None:
    """Tests, implementation, then a sweep for anything left uncommitted. The
    reviewer cannot edit any more, so the third is a safety net against a
    rework round leaving the tree dirty — `prepare_worktree` refuses a dirty
    tree on the next run — and commits nothing when there is nothing there."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()

    make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert [e for e in recorder.events if e.startswith("commit:")] == [
        "commit:test",
        "commit:feat",
        "commit:chore",
    ]


def test_a_tier_one_failure_is_kept_as_feedback(tmp_path: Path) -> None:
    """Both pilot units failed tier 1 and the runner threw the output away, so
    a retry knew nothing about what had gone wrong and re-ran both expensive
    prompts to produce the same branch. The failure is the one thing a retry
    actually needs."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder(tier1_ok=False)
    recorder.tier1_output = "E   ImportError: cannot import name 'geo' from 'src'"

    make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert "ImportError" in store.get(unit().id).feedback


def test_a_unit_retried_after_tier_one_takes_the_rework_path(tmp_path: Path) -> None:
    """With the failure recorded, the retry is one scoped run against it —
    not the full tests-then-implementation pair against a branch that already
    has both."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_feedback(unit().id, "tier 1 failed:\nE   ImportError: no module named x")
    recorder = Recorder()

    make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert len(recorder.prompts) == 1
    assert "ImportError" in recorder.prompts[0]


def test_a_resume_does_not_rebuild_what_is_already_there(tmp_path: Path) -> None:
    """Unit 2 spent twelve minutes re-running both prompts to produce a branch
    it had already produced, because the runner only discovered there was
    nothing to do after paying for both. With commits on the branch and no
    outstanding feedback, there is nothing to build — only to verify."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder(commits_from_impl=0)
    runner = make_runner(store, recorder, tmp_path)
    runner.branch_commits = lambda cwd, base: 2

    outcome = runner.run(unit(), base="main", graph=[])

    assert recorder.prompts == [], "no model call at all"
    assert "tier1" in recorder.events
    assert outcome.status == "open"


def test_a_resume_with_feedback_still_addresses_it(tmp_path: Path) -> None:
    """Commits on the branch are not a reason to ignore what review, or a tier
    1 failure, asked for."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_feedback(unit().id, "tier 1 failed:\nE   ImportError")
    recorder = Recorder()
    runner = make_runner(store, recorder, tmp_path)
    runner.branch_commits = lambda cwd, base: 2

    runner.run(unit(), base="main", graph=[])

    assert len(recorder.prompts) == 1
    assert "ImportError" in recorder.prompts[0]


def test_rework_runs_on_the_review_model(tmp_path: Path) -> None:
    """Addressing a human review is the most judgement-heavy step in the loop —
    the feedback may be imperfect, and deciding what was meant is the work. It
    ran on the implementation model because it shares `run_claude`'s plumbing,
    which is a wiring accident rather than a decision."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_feedback(unit().id, "make it a StrEnum")
    used: list[str] = []
    runner = make_runner(store, Recorder(), tmp_path)
    runner.run_rework = lambda prompt, **k: used.append("rework-model") or ""

    runner.run(unit(), base="main", graph=[])

    assert used == ["rework-model"], "rework goes through its own call, not run_claude"


def test_the_rework_prompt_allows_pushing_back(tmp_path: Path) -> None:
    """A reviewer can be wrong in a way the code cannot be. Told only to comply,
    the agent implements the mistake — StrEnum + auto() lower-cases the member
    name, so taking "StrEnum gives it this value by default" literally would
    have broken the very test it was asked to improve."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state(unit().id, IN_REVIEW, pr=16)
    store.set_feedback(unit().id, "make it a StrEnum")
    prompts: list[str] = []
    runner = make_runner(store, Recorder(), tmp_path)
    runner.run_rework = lambda prompt, **k: prompts.append(prompt) or ""

    runner.run(store.get(unit().id), base="main", graph=[])

    assert "16" in prompts[0], "it needs the PR number to reply on"
    lowered = prompts[0].lower()
    assert "what was meant" in lowered or "intent" in lowered
    assert "comment" in lowered


def approving(_: str = "") -> str:
    return '{"approved": true, "feedback": ""}'


def rejecting(reason: str) -> str:
    return json.dumps({"approved": False, "feedback": reason})


def test_an_approved_build_goes_straight_on(tmp_path: Path) -> None:
    """The cheap path, and the common one: nothing to fix, no extra rounds."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    recorder.verdicts = [approving()]

    make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert recorder.events.count("review") == 1
    assert "claude:rework" not in recorder.events


def test_a_rejected_build_is_sent_back_and_reviewed_again(tmp_path: Path) -> None:
    """The reviewer reports; the builder fixes. Previously the reviewer edited
    the branch itself, which put judgement and authorship in the same place and
    threw away anything it could only say."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    recorder.verdicts = [rejecting("the session registry leaks"), approving()]

    make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert recorder.events.count("review") == 2
    assert "claude:rework" in recorder.events
    assert "leaks" in " ".join(recorder.prompts)


def test_the_rework_prompt_carries_the_same_boundary_as_the_build(tmp_path: Path) -> None:
    """The rework is a build run too: if the reviewer's rejection points at
    something the plan gave to a later unit, the boundary has to travel with
    it, or a capable agent just implements what was only supposed to be
    reported."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(groups=(1,))])
    recorder = Recorder()
    recorder.verdicts = [rejecting("consider handling group 2's case too"), approving()]
    graph = [
        stored_unit("add-marker/1", groups=(1,)),
        stored_unit("add-marker/2", groups=(2, 3), depends_on=("add-marker/1",)),
    ]

    make_runner(store, recorder, tmp_path).run(unit(groups=(1,)), base="main", graph=graph)

    rework_prompts = [p for p in recorder.prompts if "review of this branch" in p.lower()]
    assert rework_prompts, "the rework prompt ran"
    assert "2, 3" in rework_prompts[0], "the later unit's groups are named"
    assert "leave" in rework_prompts[0].lower(), "and left alone, not implemented"


def test_the_loop_is_bounded(tmp_path: Path) -> None:
    """A reviewer that never approves would otherwise spend the window until
    the usage guard stopped it, on one unit."""
    from agent_build_kit.config import active

    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    recorder.verdicts = [rejecting("still no")] * 20

    outcome = make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert outcome.status == "held", "spent rounds hand the unit to a person"
    assert recorder.events.count("review") == active().limits.max_review_rounds
    assert "tier1" not in recorder.events, "an unapproved branch is not verified"


class MovedOnceRecorder(Recorder):
    """A push that finds the host moved the branch, then holds on the second."""

    def __init__(self) -> None:
        super().__init__()
        self.pushes = 0
        self.bodies: list[dict[str, str]] = []

    def push(self, branch: str, *, cwd: Path) -> str:
        self.pushes += 1
        if self.pushes == 1:
            raise HostMoved("the host moved the branch; adopted its head")
        return "abc123"

    def open_pr(self, unit, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
        self.bodies.append({"body": body, **bodies})
        return super().open_pr(unit, body=body, base=base, cwd=cwd)


def test_a_unit_whose_rounds_ran_out_on_a_branch_the_host_moved_is_still_held(
    tmp_path: Path,
) -> None:
    """The adoption is recorded, so a second push holds: the open points reach
    the PR rather than the unit failing with an empty note."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = MovedOnceRecorder()
    recorder.verdicts = [rejecting("the lock is still not released")] * 20

    outcome = make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert outcome.status == "held"
    assert store.get(unit().id).state == "held"
    assert store.get(unit().id).pr == 7
    assert recorder.pushes == 2
    assert "the lock is still not released" in recorder.bodies[-1]["body"]


def test_a_held_pull_request_is_given_both_bodies(tmp_path: Path) -> None:
    """The host, not this step, knows whether it shows the order: a held PR
    offers the unstacked body and the stacked one, open points in each."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = MovedOnceRecorder()
    recorder.verdicts = [rejecting("the lock is still not released")] * 20

    make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    stacked = recorder.bodies[-1]["stacked_body"]
    assert "the lock is still not released" in stacked
    assert "Stacked on" not in stacked


def test_what_the_reviewer_last_said_survives_the_failure(tmp_path: Path) -> None:
    """A unit that ran out of rounds is retried by a human, and the retry needs
    to know what the reviewer kept objecting to."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    recorder.verdicts = [rejecting("the lock is still not released on error")] * 20

    make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert "lock is still not released" in store.get(unit().id).feedback


def test_an_unreadable_verdict_does_not_pass_the_branch(tmp_path: Path) -> None:
    """A reviewer whose answer cannot be parsed has not approved anything.
    Reading it as approval would make a broken reviewer invisible. The rounds
    run out with the branch never approved, which is a hold, not a failure:
    the branch is pushed and a person inherits it."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    recorder.verdicts = ["I think it looks fine, honestly"] * 20

    outcome = make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert outcome.status == "held"
    assert store.get(unit().id).approved == ""
    assert "not readable as a verdict" in store.get(unit().id).feedback


def test_a_unit_stops_when_its_upstream_goes_back_for_rework(tmp_path: Path) -> None:
    """Its work is built on the parent's code. Carrying on reviewing and
    pushing against a base that is about to change spends the window on work
    that may need redoing, and can open a PR whose diff includes the parent's
    old commits."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    runner = make_runner(store, recorder, tmp_path)
    runner.upstream_incomplete = lambda u: "add-marker/0 went back for rework"

    outcome = runner.run(unit(), base="spec/add-marker/0", graph=[])

    assert outcome.status == "held"
    assert "rework" in outcome.detail
    assert "push" not in recorder.events, "nothing is pushed against a base that moved"


def test_a_held_unit_finishes_the_step_it_was_in(tmp_path: Path) -> None:
    """Abandoning mid-step throws away whatever that step produced. The build
    runs and commits; the hold happens at the boundary."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    runner = make_runner(store, recorder, tmp_path)
    runner.upstream_incomplete = lambda u: "upstream reworking"

    runner.run(unit(), base="main", graph=[])

    assert "commit:test" in recorder.events, "the tests step's work is committed, not discarded"
    assert "claude:impl" not in recorder.events, "and the next step does not start"


def test_a_held_unit_goes_back_to_planned_so_it_resumes(tmp_path: Path) -> None:
    """`planned` is what the dependency check already gates on, so the unit
    resumes by itself once the upstream is open again — no separate state and
    no separate resume path."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    runner = make_runner(store, recorder, tmp_path)
    runner.upstream_incomplete = lambda u: "upstream reworking"

    runner.run(unit(), base="main", graph=[])

    assert store.get(unit().id).state == PLANNED
    assert "held" in str(store.get(unit().id).history[-1])


def test_a_unit_whose_parent_merged_while_it_built_stops_before_pushing(tmp_path: Path) -> None:
    """The merge leaves a building branch where it is rather than rebase the
    tree in use, so the build must notice itself. Going on would open its PR
    against the merged branch; stopping at the step boundary lets the resume's
    restack put it on its new base first."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    runner = make_runner(store, recorder, tmp_path)
    runner.base_moved = lambda u, base, **kw: f"its base moved from {base} to main while it built"

    outcome = runner.run(unit(), base="spec/add-marker/0", graph=[])

    assert outcome.status == "held"
    assert "push" not in recorder.events and "pr" not in recorder.events
    assert store.get(unit().id).state == PLANNED
    assert store.get(unit().id).resume_from == "implement", "resumes at the step it stopped before"


def test_a_unit_whose_base_was_rewritten_while_it_built_stops_before_pushing(
    tmp_path: Path,
) -> None:
    """Its parent was restacked mid-pass — the grandparent merged — so the base
    keeps its name but not the commits this unit sits on. Pushing would open a
    PR repeating the parent's old commits; the hold lets the resume's restack
    move it first. The check is against the tip the run started on."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    runner = make_runner(store, recorder, tmp_path)
    runner.base_tip = lambda tree, ref: f"tip of {ref}"
    seen: list[tuple] = []

    def base_moved(u, base, *, tree, start):
        seen.append((tree, start))
        # the restack lands while the review runs, after implement
        return "its base spec/add-marker/0 was rewritten" if "review" in recorder.events else ""

    runner.base_moved = base_moved

    outcome = runner.run(unit(), base="spec/add-marker/0", graph=[])

    assert "claude:impl" in recorder.events, "implement ran before the rewrite"
    assert outcome.status == "held"
    assert "rewritten" in outcome.detail
    assert "push" not in recorder.events and "pr" not in recorder.events
    assert store.get(unit().id).state == PLANNED
    assert store.get(unit().id).resume_from == "verify"
    assert seen and all(s == (tmp_path / "tree", "tip of spec/add-marker/0") for s in seen)


def test_the_base_s_tip_is_recorded_before_a_resume_restacks(tmp_path: Path) -> None:
    """The tip the build is placed on, not the one after the restack: taken
    later, a base rewritten during the restack would be the tip compared
    against, and every check would pass."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={
            "branch_commits": lambda cwd, base: 2,
            "base_tip": lambda tree, ref: recorder.events.append("base_tip") or "t",
            "restack_onto": lambda **kw: recorder.events.append("restack") or None,
        }
    )

    runner.run(unit(), base="spec/add-marker/0", graph=[])

    assert recorder.events.index("base_tip") < recorder.events.index("restack")


def test_a_base_rewritten_while_a_resume_adapts_holds_the_build(tmp_path: Path) -> None:
    """The adapt runs a model for minutes. A parent restacked meanwhile — its
    own parent merged — rewrites the base under the same name, and the unit,
    reset onto the old tip, would push the parent's pre-rebase commits."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    tip = ["before"]
    answer = json.dumps({"tests": [{"name": "test_click", "decision": "keep"}]})

    def adapt(prompt: str, *, cwd: Path) -> str:
        tip[0] = "rewritten"  # the parent is restacked while the port runs
        return answer

    def base_moved(u, base, *, tree, start):
        return f"its base {base} was rewritten" if start != tip[0] else ""

    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={
            "branch_commits": lambda cwd, base: 2,
            "base_tip": lambda tree, ref: tip[0],
            "restack_onto": lambda **kw: _restacked(conflict="x", old_tests=("test_click",)),
            "reset_to": lambda tree, onto, keep: None,
            "tests_in": lambda tree: {"test_click"},
            "run_rework": adapt,
            "base_moved": base_moved,
        }
    )

    outcome = runner.run(unit(), base="spec/add-marker/0", graph=[])

    assert tip == ["rewritten"], "the adapt ran"
    assert outcome.status == "held"
    assert "rewritten" in outcome.detail
    assert "push" not in recorder.events and "pr" not in recorder.events
    assert store.get(unit().id).state == PLANNED


def test_nothing_holds_when_the_upstream_is_fine(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()

    assert (
        make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[]).status == "open"
    )


def test_a_resuming_unit_restacks_before_anything_else(tmp_path: Path) -> None:
    """Its parent was reworked and force-pushed while this unit was held, so the
    branch it sits on no longer contains the commits underneath it. Verifying or
    reviewing first would judge the unit against a base it does not have."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    runner = make_runner(store, recorder, tmp_path)
    runner.branch_commits = lambda cwd, base: 2
    runner.restack_onto = lambda **kw: (
        recorder.events.append("restack")
        or Restacked(onto_unit="c/1", onto_intent="parent", old_base="a", old_head="b")
    )

    runner.run(unit(), base="spec/add-marker/0", graph=[])

    assert recorder.events[0] == "restack", "before the review, the checks and the push"


def test_a_unit_whose_base_has_not_moved_is_not_restacked(tmp_path: Path) -> None:
    """A rebase rewrites every commit on the branch, which invalidates any
    check already run against it. Not worth doing when nothing moved."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    runner = make_runner(store, recorder, tmp_path)
    runner.branch_commits = lambda cwd, base: 2
    runner.restack_onto = lambda **kw: None

    runner.run(unit(), base="main", graph=[])

    assert "restack" not in recorder.events


def test_a_conflicted_restack_fails_the_unit_rather_than_guessing(tmp_path: Path) -> None:
    """`move_branch_onto` resolves what it can and raises otherwise. Carrying on
    would verify a half-rebased branch; the conflict is left for a human with
    the reason recorded."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    runner = make_runner(store, recorder, tmp_path)
    runner.branch_commits = lambda cwd, base: 2

    def conflicted(**kw):
        raise RuntimeError("both sides changed sessions.py")

    runner.restack_onto = conflicted

    outcome = runner.run(unit(), base="spec/add-marker/0", graph=[])

    assert outcome.status == "failed"
    assert "sessions.py" in store.get(unit().id).feedback
    assert "push" not in recorder.events


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
    """A spent window or a killed run says nothing about the branch: it
    reaches the tick, which pauses or reclaims, and the unit is not failed."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    runner = make_runner(store, recorder, tmp_path)
    runner.branch_commits = lambda cwd, base: 2

    def refused(**kw):
        raise refusal

    runner.restack_onto = refused

    with pytest.raises(type(refusal)):
        runner.run(unit(), base="spec/add-marker/0", graph=[])

    assert store.get(unit().id).state != "failed"
    assert "conflicted" not in store.get(unit().id).feedback


def test_a_fresh_unit_has_nothing_to_restack(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    runner = make_runner(store, recorder, tmp_path)
    runner.restack_onto = lambda **kw: (
        recorder.events.append("restack")
        or Restacked(onto_unit="c/1", onto_intent="parent", old_base="a", old_head="b")
    )

    runner.run(unit(), base="main", graph=[])

    assert "restack" not in recorder.events, "no commits yet, so no base to have moved"


def test_the_log_says_which_step_a_unit_is_on(tmp_path: Path) -> None:
    """A build is several twenty-minute runs; the tick log used to go quiet
    from "ready" until the end, so the only way to see progress was to go and
    read the worktree."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    lines: list[str] = []
    runner = make_runner(store, Recorder(), tmp_path).model_copy(update={"log": lines.append})

    runner.run(unit(), base="main", graph=[])

    steps = [line for line in lines if line.startswith("step: ")]
    assert [s.split(" (")[0] for s in steps] == [
        "step: write the tests",
        "step: implement",
        "step: review round 1",
        "step: tier 1",
    ]
    assert lines[-1].startswith("in review: PR #")


class Gate:
    """A usage guard that says yes a set number of times, then no."""

    def __init__(self, yes: int) -> None:
        self.yes = yes

    def __call__(self) -> tuple[bool, str]:
        self.yes -= 1
        return (self.yes >= 0, "usage fine" if self.yes >= 0 else "session usage at 75%")


def test_usage_is_checked_before_every_step_not_only_at_the_start(tmp_path: Path) -> None:
    """A unit loops — build, review, rework, review — and each step is a long
    Claude run. Checked only on starting, a unit ran on for hours past the
    threshold once it had begun."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    runner = make_runner(store, recorder, tmp_path).model_copy(update={"may_start": Gate(1)})

    outcome = runner.run(unit(), base="main", graph=[])

    assert outcome.status == "paused"
    assert recorder.events == ["claude:tests", "commit:test"]
    assert store.get(unit().id).state == PLANNED
    assert store.get(unit().id).resume_from == "implement"


def test_a_paused_unit_resumes_at_the_step_it_stopped_before(tmp_path: Path) -> None:
    """Not from the top: the tests are already written and committed."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state(unit().id, PLANNED, resume_from="implement")
    recorder = Recorder()

    make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert recorder.events[:2] == ["claude:impl", "commit:feat"]
    assert "claude:tests" not in recorder.events


def test_a_unit_held_before_review_is_still_reviewed_when_it_resumes(tmp_path: Path) -> None:
    """The bug this replaced: a unit held after its build came back to a
    branch with commits and no feedback, read that as finished and already
    reviewed work, and went straight to tier 1."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state(unit().id, PLANNED, resume_from="review")
    recorder = Recorder()
    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={"branch_commits": lambda cwd, base: 2}
    )

    runner.run(unit(), base="main", graph=[])

    assert [e for e in recorder.events if not e.startswith("commit:")][0] == "review"
    assert "claude:impl" not in recorder.events


def test_a_pause_between_review_and_rework_keeps_what_review_asked_for(tmp_path: Path) -> None:
    """Stopped after a review asked for changes, the resume should make them —
    not review the same branch again and pay for the same verdict twice."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    recorder.verdicts = ['{"approved": false, "feedback": "name it better"}']
    # Yes for the start, before implement and before review; no before rework.
    runner = make_runner(store, recorder, tmp_path).model_copy(update={"may_start": Gate(3)})

    assert runner.run(unit(), base="main", graph=[]).status == "paused"
    stored = store.get(unit().id)
    assert stored.feedback == "name it better"
    assert stored.resume_from == "rework"


def test_resuming_is_forgotten_once_the_unit_is_in_review(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state(unit().id, PLANNED, resume_from="implement")

    make_runner(store, Recorder(), tmp_path).run(unit(), base="main", graph=[])

    assert store.get(unit().id).resume_from == ""


def test_a_rework_of_an_open_pr_posts_its_replies_after_the_push(tmp_path: Path) -> None:
    """After, so a reply describes code the reviewer can already see."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))
    store.set_feedback(unit().id, "[comment 11] a.py:3 — rename")
    recorder = Recorder()
    replies: list[dict] = []

    def reply(**kwargs) -> None:
        recorder.events.append("reply")
        replies.append(kwargs)

    runner = make_runner(store, recorder, tmp_path).model_copy(update={"reply": reply})
    runner.run(store.get(unit().id), base="main", graph=[])

    assert recorder.events.index("reply") > recorder.events.index("push")
    assert replies[0]["pr"] == 7 and replies[0]["answer_text"] == "done"


def test_a_first_build_has_nobody_to_reply_to(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    replies: list[dict] = []
    runner = make_runner(store, Recorder(), tmp_path).model_copy(
        update={"reply": lambda **kwargs: replies.append(kwargs)}
    )

    runner.run(unit(), base="main", graph=[])

    assert replies == []


def test_no_rework_follows_the_last_review(tmp_path: Path) -> None:
    """Nothing would review it: the unit goes to a person either way, having
    paid for a rework nobody sees."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    recorder.verdicts = ['{"approved": false, "feedback": "no"}'] * 3

    outcome = make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert outcome.status == "held"
    assert recorder.events.count("review") == 3
    assert recorder.events.count("claude:rework") == 2


def _tasks_file(tmp_path: Path) -> Path:
    tasks = tmp_path / "meta" / "openspec" / "changes" / "add-marker" / "tasks.md"
    tasks.parent.mkdir(parents=True)
    tasks.write_text("## 1. [app] [tier1] G\n- [ ] 1.1 Test: a\n- [ ] 1.2 Do a\n")
    return tasks


def test_tasks_are_ticked_when_the_unit_is_through_the_loop_not_before(tmp_path: Path) -> None:
    """Ticked by the pipeline once review approved, tier 1 passed and the work
    is pushed — never by a build that has merely finished."""
    tasks = _tasks_file(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    seen_at_review: list[str] = []
    recorder = Recorder()
    original_review = recorder.review

    def review(*, cwd: Path, context: str = "") -> str:
        seen_at_review.append(tasks.read_text())
        return original_review(cwd=cwd)

    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={"run_review": review, "run_rework_review": review}
    )
    runner.run(unit(), base="main", graph=[])

    assert "- [ ]" in seen_at_review[0], "not yet ticked while under review"
    assert tasks.read_text().count("- [x]") == 2


def test_a_failed_unit_leaves_its_tasks_unticked(tmp_path: Path) -> None:
    tasks = _tasks_file(tmp_path)
    tasks.write_text(tasks.read_text().replace("- [ ]", "- [x]"))  # a build agent's doing
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder(tier1_ok=False)

    make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert "- [x]" not in tasks.read_text()


class SelfCommitting(Recorder):
    """An agent that commits its own work, leaving the pipeline nothing."""

    def claude(self, prompt: str, *, cwd: Path) -> str:
        self.made += 1
        return super().claude(prompt, cwd=cwd)

    def commit(self, message: str, *, cwd: Path) -> int:
        self.events.append(f"commit:{message.split(':')[0]}")
        return 0


def test_a_build_the_agent_committed_itself_is_still_reviewed(tmp_path: Path) -> None:
    """Read from the commit step, it looked like the run produced nothing."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = SelfCommitting()

    outcome = make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert outcome.status == "open"
    assert "review" in recorder.events


def test_a_rework_is_always_reviewed(tmp_path: Path) -> None:
    """When the rework agent commits its change itself, the pipeline's commit
    finds nothing, and the branch — carrying rounds its review had rejected —
    would go to the PR with no review at all."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))
    store.set_feedback(unit().id, "rename it")
    recorder = SelfCommitting()

    make_runner(store, recorder, tmp_path).run(store.get(unit().id), base="main", graph=[])

    assert recorder.events.index("review") < recorder.events.index("push")


def test_a_unit_resumed_before_a_rework_review_gets_the_rework_reviewer(tmp_path: Path) -> None:
    """Which reviewer judges depends on whether the review follows a rework,
    and a resume no longer carries the feedback that used to say so. Resumed
    by hand, a rework would go to the standard reviewer."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state(unit().id, PLANNED, resume_from="rework_review")
    recorder = Recorder()
    used: list[str] = []
    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={
            "branch_commits": lambda cwd, base: 2,
            "run_review": lambda *, cwd, context="": (
                used.append("standard") or recorder.review(cwd=cwd)
            ),
            "run_rework_review": lambda *, cwd, context="": (
                used.append("rework") or recorder.review(cwd=cwd)
            ),
        }
    )

    runner.run(unit(), base="main", graph=[])

    assert used == ["rework"]


def test_each_step_is_recorded_as_it_starts(tmp_path: Path) -> None:
    """So a run killed inside a step resumes at it. Without this, a run killed
    mid-build came back to a branch with only its tests, and the "branch
    already has the work" path sent tests alone to review."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    seen: list[str] = []
    original_claude, original_review = recorder.claude, recorder.review

    def claude(prompt: str, *, cwd: Path) -> str:
        seen.append(store.get(unit().id).resume_from)
        return original_claude(prompt, cwd=cwd)

    def review(*, cwd: Path, context: str = "") -> str:
        seen.append(store.get(unit().id).resume_from)
        return original_review(cwd=cwd)

    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={"run_claude": claude, "run_review": review, "run_rework_review": review}
    )
    runner.run(unit(), base="main", graph=[])

    assert seen == ["tests", "implement", "review"]
    assert store.get(unit().id).resume_from == "", "cleared once in review"


def test_a_run_killed_while_writing_tests_writes_them_again(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state(unit().id, PLANNED, resume_from="tests")
    recorder = Recorder()
    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={"branch_commits": lambda cwd, base: recorder.made + 1}
    )

    runner.run(unit(), base="main", graph=[])

    assert recorder.events[0] == "claude:tests"


def test_replies_survive_a_pause_between_the_rework_and_the_push(tmp_path: Path) -> None:
    """A rework writes replies to review threads, its review asks for more,
    the unit pauses for usage before the push, and the replies go with the
    process. Kept on the unit, the run that finally pushes posts them."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))
    store.set_feedback(unit().id, "[comment 11] a.py:3 — rename")
    recorder = Recorder()
    recorder.verdicts = ['{"approved": false, "feedback": "and the docs"}']
    posted: list[str] = []

    # Yes at the start and before the review; no before the loop's rework.
    first = make_runner(store, recorder, tmp_path).model_copy(
        update={"may_start": Gate(2), "reply": lambda **k: posted.append(k["answer_text"])}
    )
    assert first.run(store.get(unit().id), base="main", graph=[]).status == "paused"
    assert posted == []
    assert store.get(unit().id).pending_replies == ("done",)

    second = make_runner(store, recorder, tmp_path).model_copy(
        update={"reply": lambda **k: posted.append(k["answer_text"])}
    )
    second.run(store.get(unit().id), base="main", graph=[])

    assert posted == ["done"]
    assert store.get(unit().id).pending_replies == ()


def test_resuming_before_a_loop_rework_answers_the_reviewer_not_the_pr(tmp_path: Path) -> None:
    """That feedback is the loop's own reviewer's. Run as PR feedback, its
    summary was posted to the PR, telling the human "you asked" for things
    only the reviewer had."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state(unit().id, PLANNED, pr=4, resume_from="rework")
    store.set_feedback(unit().id, "render it as a tree")
    recorder = Recorder()
    posted: list[str] = []
    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={"reply": lambda **k: posted.append(k["answer_text"])}
    )

    runner.run(store.get(unit().id), base="main", graph=[])

    assert recorder.prompts[0].startswith("A review of this branch asked for changes")
    assert posted == []


def test_work_is_built_on_the_remote_trunk_but_the_pr_targets_main(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    worktree_bases: list[str] = []
    pr_bases: list[str] = []
    original_open_pr = recorder.open_pr

    def open_pr(u, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
        pr_bases.append(base)
        return original_open_pr(u, body=body, base=base, cwd=cwd)

    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={
            "worktree": lambda u, base: worktree_bases.append(base) or tmp_path / "tree",
            "open_pr": open_pr,
        }
    )
    runner.run(unit(), base="main", graph=[])

    assert worktree_bases == ["origin/main"]
    assert pr_bases == ["main"]


def _bodies_sent(tmp_path: Path, *, linear: bool) -> dict[str, str]:
    """What the runner hands `open_pr` for a unit stacked on an open parent."""
    parent = stored_unit("add-marker/1", state=IN_REVIEW, pr=4, branch="spec/add-marker/1")
    child = unit("add-marker/2", depends_on=("add-marker/1",))
    store = UnitStore(tmp_path / "units.json")
    store.upsert([parent, child])
    sent: dict[str, str] = {}

    def open_pr(u, *, body: str, base: str, cwd: Path, stacked_body: str) -> int:
        sent.update(body=body, stacked_body=stacked_body)
        return 7

    runner = make_runner(store, Recorder(), tmp_path).model_copy(
        update={"open_pr": open_pr, "linear": lambda tree, base: linear}
    )
    runner.run(child, base="spec/add-marker/1", graph=[parent, store.get(child.id)])
    return sent


def test_the_body_leaves_the_order_to_a_host_that_renders_stacks(tmp_path: Path) -> None:
    """Both bodies go to `open_pr`, which alone learns whether the host put
    the PR in a stack: the one for no stack states the order, the other
    leaves it to the host."""
    sent = _bodies_sent(tmp_path, linear=True)

    assert "Stacked on" in sent["body"]
    assert "Stacked on" not in sent["stacked_body"]


@pytest.mark.parametrize("which", ["body", "stacked_body"])
def test_a_branch_left_off_its_base_is_reported_as_not_linear(tmp_path: Path, which: str) -> None:
    """Checked in the tree by the runner, not assumed: whichever body the
    PR ends up with says the chain cannot merge until it is rebased."""
    assert "not linear" in _bodies_sent(tmp_path, linear=False)[which].lower()
    assert "not linear" not in _bodies_sent(tmp_path / "linear", linear=True)[which].lower()


def test_a_branch_the_host_moved_is_re_reviewed_rather_than_pushed(tmp_path: Path) -> None:
    """The push step found the host's head is not what was last pushed, and
    adopted it: the unit goes back through review, and no PR is touched."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()

    def push(branch: str, *, cwd: Path) -> str:
        raise HostMoved("the host moved it")

    runner = make_runner(store, recorder, tmp_path).model_copy(update={"push": push})
    outcome = runner.run(unit(), base="main", graph=[])

    assert outcome.status == "held"
    assert "pr" not in recorder.events
    assert store.get(unit().id).state == PLANNED
    assert store.get(unit().id).resume_from == "rework_review"


def test_a_failed_restack_keeps_the_review_feedback_already_waiting(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_feedback(unit().id, "make hover work on non-widgets")
    recorder = Recorder()
    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={"branch_commits": lambda cwd, base: 2}
    )

    def conflicted(**kwargs) -> Restacked | None:
        raise RuntimeError("the resolution dropped a test")

    runner.restack_onto = conflicted
    runner.run(unit(), base="spec/add-marker/0", graph=[])

    feedback = store.get(unit().id).feedback
    assert "make hover work on non-widgets" in feedback
    assert "dropped a test" in feedback


def _restacked(**overrides) -> Restacked:
    fields: dict = {
        "onto_unit": "c/2",
        "onto_intent": "the MCP surface",
        "old_base": "a",
        "old_head": "b",
    }
    return Restacked(**{**fields, **overrides})


def _reviews_seen(recorder: Recorder) -> tuple[list[str], list[str]]:
    """(which reviewer, context given) for each review."""
    who: list[str] = []
    contexts: list[str] = []
    original = recorder.review

    def standard(*, cwd: Path, context: str = "") -> str:
        who.append("standard")
        contexts.append(context)
        return original(cwd=cwd)

    def rework(*, cwd: Path, context: str = "") -> str:
        who.append("rework")
        contexts.append(context)
        return original(cwd=cwd)

    recorder.standard_review, recorder.rework_review = standard, rework  # type: ignore[attr-defined]
    return who, contexts


def test_a_restack_that_needed_resolving_is_reviewed_for_whether_its_tests_still_fit(
    tmp_path: Path,
) -> None:
    """The predecessor changed underneath this unit and a resolver rewrote its
    code: the unit's tests may now assert behaviour the predecessor removed."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    who, contexts = _reviews_seen(recorder)
    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={
            "branch_commits": lambda cwd, base: 2,
            "restack_onto": lambda **kw: _restacked(resolved=("src/mcp.py",)),
            "run_review": recorder.standard_review,  # type: ignore[attr-defined]
            "run_rework_review": recorder.rework_review,  # type: ignore[attr-defined]
        }
    )

    runner.run(unit(), base="spec/c/2", graph=[])

    assert who == ["rework"], "judged by the rework reviewer (fable)"
    assert "moved onto an updated predecessor" in contexts[0]
    assert "src/mcp.py" in contexts[0]
    assert "check each of this unit's tests" in contexts[0]
    assert store.get(unit().id).predecessor_note == "", "cleared once in review"


def test_a_restack_that_could_not_be_merged_is_ported_and_its_tests_accounted_for(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    who, contexts = _reviews_seen(recorder)
    resets: list[tuple[str, str]] = []
    answer = json.dumps(
        {
            "tests": [
                {"name": "test_click", "decision": "keep", "reason": ""},
                {
                    "name": "test_console",
                    "decision": "retire",
                    "reason": "the predecessor made console capture opt-in, so this is moot",
                },
            ],
            "summary": "ported",
        }
    )
    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={
            "branch_commits": lambda cwd, base: 2,
            "restack_onto": lambda **kw: _restacked(
                conflict="dropped test_console", old_tests=("test_click", "test_console")
            ),
            "reset_to": lambda tree, onto, keep: resets.append((onto, keep)),
            "tests_in": lambda tree: {"test_click"},
            "run_rework": lambda prompt, *, cwd: recorder.prompts.append(prompt) or answer,
            "run_review": recorder.standard_review,  # type: ignore[attr-defined]
            "run_rework_review": recorder.rework_review,  # type: ignore[attr-defined]
        }
    )

    outcome = runner.run(unit(), base="spec/c/2", graph=[])

    assert resets == [("spec/c/2", "refs/spec-driven/pre-adapt/add-marker/1")]
    assert "`test_console`" in recorder.prompts[0], "the port is told which tests to account for"
    assert "test_console`: retire — the predecessor made console capture opt-in" in contexts[0]
    assert outcome.status == "open"


def test_a_port_that_silently_drops_a_test_fails(tmp_path: Path) -> None:
    """The thing the accounting exists for: a port can end a conflict by
    leaving out what it could not carry over."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    answer = json.dumps({"tests": [{"name": "test_click", "decision": "keep"}]})
    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={
            "branch_commits": lambda cwd, base: 2,
            "restack_onto": lambda **kw: _restacked(
                conflict="x", old_tests=("test_click", "test_console")
            ),
            "reset_to": lambda tree, onto, keep: None,
            "tests_in": lambda tree: {"test_click"},
            "run_rework": lambda prompt, *, cwd: answer,
        }
    )

    outcome = runner.run(unit(), base="spec/c/2", graph=[])

    assert outcome.status == "failed"
    assert "no decision for `test_console`" in store.get(unit().id).feedback
    assert "push" not in recorder.events


def test_a_failed_accounting_names_the_outstanding_tests(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    answer = json.dumps({"tests": [{"name": "test_click", "decision": "keep"}]})
    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={
            "branch_commits": lambda cwd, base: 2,
            "restack_onto": lambda **kw: _restacked(
                conflict="x", old_tests=("test_click", "test_console", "test_drag")
            ),
            "reset_to": lambda tree, onto, keep: None,
            "tests_in": lambda tree: {"test_click"},
            "run_rework": lambda prompt, *, cwd: answer,
        }
    )

    outcome = runner.run(unit(), base="spec/c/2", graph=[])

    assert outcome.status == "failed"
    assert "outstanding: `test_console`, `test_drag`" in store.get(unit().id).feedback


def test_what_counts_as_accounting_for_a_test() -> None:
    from agent_build_kit.pipeline.stack_runner import PortedTest, check_test_decisions

    def d(name: str, decision: str, reason: str = "") -> PortedTest:
        return PortedTest(name=name, decision=decision, reason=reason)

    present = {"test_a", "test_b_v2"}
    assert check_test_decisions(["test_a"], [d("test_a", "keep")], present) == []
    assert (
        check_test_decisions(
            ["test_b"], [d("test_b", "adapt", "renamed to test_b_v2 for the new shape")], present
        )
        == []
    )
    assert check_test_decisions(["test_c"], [d("test_c", "retire", "moot")], present) == [
        "`test_c` retired without a reason naming the predecessor's change"
    ]
    assert check_test_decisions(["test_d"], [d("test_d", "keep")], present) == [
        "`test_d` is marked keep but is not in the tree"
    ]


def test_a_changed_test_cannot_be_answered_keep() -> None:
    from agent_build_kit.pipeline.stack_runner import PortedTest, check_test_decisions

    present = {"test_a"}
    kept = [PortedTest(name="test_a", decision="keep")]
    adapted = [PortedTest(name="test_a", decision="adapt", reason="relaxed to fit the new shape")]

    problems = check_test_decisions(["test_a"], kept, present, changed={"test_a"})
    assert problems == [
        "`test_a` is marked keep but differs from the previous work — mark it "
        "adapt and say what changed"
    ]
    assert check_test_decisions(["test_a"], adapted, present, changed={"test_a"}) == []
    assert check_test_decisions(["test_a"], [], present, changed={"test_a"}) == [
        "no decision for `test_a`, which differs from the previous work — mark it "
        "adapt and say what changed, or retire it with a reason"
    ]
    assert check_test_decisions(["test_b"], [], present=set(), changed={"test_b"}) == [
        "no decision for `test_b`, which is no longer in the tree — retire it with a reason "
        "naming what in the predecessor made it invalid, or mark it adapt and name the test "
        "that replaced it"
    ]


def test_only_the_uncertain_tests_need_a_decision() -> None:
    """A test the replay left alone is not asked about at all; one that
    vanished, or that survived in changed form, still must be."""
    from agent_build_kit.pipeline.stack_runner import tests_needing_decision

    # present and unchanged by the replay: no decision required
    assert tests_needing_decision(["test_a"], present={"test_a"}, changed=set()) == []
    # missing from the tree: still required
    assert tests_needing_decision(["test_b"], present=set(), changed=set()) == ["test_b"]
    # present, but the replay changed it: still required
    assert tests_needing_decision(["test_c"], present={"test_c"}, changed={"test_c"}) == ["test_c"]
    # a mix keeps only the uncertain ones
    assert tests_needing_decision(
        ["test_a", "test_b", "test_c"], present={"test_a", "test_c"}, changed={"test_c"}
    ) == ["test_b", "test_c"]


def test_the_silent_drop_guard_still_holds_over_the_narrowed_list() -> None:
    """Narrowing which tests must be accounted for must not narrow what makes
    an accounting wrong: a false keep or a bare retirement is still a problem
    once the test is one of the ones actually asked about."""
    from agent_build_kit.pipeline.stack_runner import (
        PortedTest,
        check_test_decisions,
        tests_needing_decision,
    )

    old_tests = ["test_a", "test_b"]
    present = {"test_a"}  # test_b vanished in the replay
    required = tests_needing_decision(old_tests, present=present, changed=set())

    claims_kept = [
        PortedTest(name="test_a", decision="keep"),
        PortedTest(name="test_b", decision="keep"),
    ]
    assert check_test_decisions(required, claims_kept, present) == [
        "`test_b` is marked keep but is not in the tree"
    ]

    bare_retirement = [
        PortedTest(name="test_a", decision="keep"),
        PortedTest(name="test_b", decision="retire", reason="moot"),
    ]
    assert check_test_decisions(required, bare_retirement, present) == [
        "`test_b` retired without a reason naming the predecessor's change"
    ]


def test_a_test_the_replay_left_alone_is_not_required_in_the_accounting(
    tmp_path: Path,
) -> None:
    """The runner can see for itself that a test is present and untouched, so
    the agent is not asked to restate it — only `test_console`, which the
    replay actually dropped, needs a decision."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    who, contexts = _reviews_seen(recorder)
    answer = json.dumps(
        {
            "tests": [
                {
                    "name": "test_console",
                    "decision": "retire",
                    "reason": "the predecessor made console capture opt-in, so this is moot",
                },
            ],
            "summary": "ported",
        }
    )
    # Empty until the port (the run_rework call) has actually happened, as the
    # real reset-then-port does: nothing of the unit's own is in the tree
    # right after the reset.
    ported: list[bool] = []

    def run_rework(prompt: str, *, cwd: Path) -> str:
        ported.append(True)
        return answer

    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={
            "branch_commits": lambda cwd, base: 2,
            "restack_onto": lambda **kw: _restacked(
                conflict="x", old_tests=("test_click", "test_console")
            ),
            "reset_to": lambda tree, onto, keep: None,
            # test_console dropped; test_click stayed
            "tests_in": lambda tree: {"test_click"} if ported else set(),
            "tests_changed": lambda tree, ref: set(),  # test_click's content is untouched
            "run_rework": run_rework,
            "run_review": recorder.standard_review,  # type: ignore[attr-defined]
            "run_rework_review": recorder.rework_review,  # type: ignore[attr-defined]
        }
    )

    outcome = runner.run(unit(), base="spec/c/2", graph=[])

    assert outcome.status == "open", "test_click needed no decision, so nothing was missing"
    assert "counted as kept without being asked about" in contexts[0]
    assert "`test_click`" in contexts[0]
    assert "`test_console`: retire" in contexts[0]


def test_a_kept_test_ported_after_the_reset_passes_the_keep_check(tmp_path: Path) -> None:
    """`present` and `required` must be read after the port, not right after
    the reset: sampled then, the tree is empty of the unit's own tests, a
    correct `keep` for one it carried over is checked against that empty
    snapshot, and the unit fails on work it actually did."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    answer = json.dumps({"tests": [{"name": "test_click", "decision": "keep"}]})
    ported: list[bool] = []

    def run_rework(prompt: str, *, cwd: Path) -> str:
        ported.append(True)
        return answer

    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={
            "branch_commits": lambda cwd, base: 2,
            "restack_onto": lambda **kw: _restacked(conflict="x", old_tests=("test_click",)),
            "reset_to": lambda tree, onto, keep: None,
            "tests_in": lambda tree: {"test_click"} if ported else set(),
            "tests_changed": lambda tree, ref: set(),
            "run_rework": run_rework,
        }
    )

    outcome = runner.run(unit(), base="spec/c/2", graph=[])

    assert outcome.status == "open"


def test_a_changed_test_still_requires_a_decision(tmp_path: Path) -> None:
    """A test that survived the replay by name only — present, but weakened —
    still needs an accounting, and `tests_changed` is read against the old
    work's own ref, after the port has actually landed."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    no_decision = json.dumps({"tests": []})
    refs_seen: list[str] = []

    def tests_changed(tree: Path, ref: str) -> set[str]:
        refs_seen.append(ref)
        assert recorder.events.count("commit:adapt") == 1, "called after the adapt commit"
        return {"test_click"}

    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={
            "branch_commits": lambda cwd, base: 2,
            "restack_onto": lambda **kw: _restacked(conflict="x", old_tests=("test_click",)),
            "reset_to": lambda tree, onto, keep: None,
            "tests_in": lambda tree: {"test_click"},
            "tests_changed": tests_changed,
            "run_rework": lambda prompt, *, cwd: recorder.prompts.append(prompt) or no_decision,
        }
    )

    outcome = runner.run(unit(), base="spec/c/2", graph=[])

    assert refs_seen == [f"refs/spec-driven/pre-adapt/{unit().id}"]
    assert outcome.status == "failed"
    assert "no decision for `test_click`" in store.get(unit().id).feedback
    assert "test_click" in recorder.prompts[1], "the follow-up names it"


def test_an_incomplete_accounting_is_asked_again_before_the_unit_fails(
    tmp_path: Path,
) -> None:
    """One decision missing is put back to the agent, naming it, rather than
    failing a unit whose ported code already landed."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    incomplete = json.dumps({"tests": [{"name": "test_click", "decision": "keep"}]})
    complete = json.dumps(
        {
            "tests": [
                {"name": "test_click", "decision": "keep"},
                {
                    "name": "test_console",
                    "decision": "retire",
                    "reason": "the predecessor made console capture opt-in, so this is moot",
                },
            ]
        }
    )
    answers = [incomplete, complete]
    ported: list[bool] = []

    def run_rework(prompt: str, *, cwd: Path) -> str:
        ported.append(True)
        recorder.prompts.append(prompt)
        return answers[len(recorder.prompts) - 1]

    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={
            "branch_commits": lambda cwd, base: 2,
            "restack_onto": lambda **kw: _restacked(
                conflict="x", old_tests=("test_click", "test_console")
            ),
            "reset_to": lambda tree, onto, keep: None,
            "tests_in": lambda tree: {"test_click"} if ported else set(),
            "tests_changed": lambda tree, ref: set(),
            "run_rework": run_rework,
        }
    )

    outcome = runner.run(unit(), base="spec/c/2", graph=[])

    assert len(recorder.prompts) == 2, "asked again rather than failed on the first miss"
    assert "test_console" in recorder.prompts[1], "told which decision was still outstanding"
    assert recorder.events.count("commit:adapt") == 1, "the ported code is not rebuilt for the ask"
    assert outcome.status == "open"


def test_an_accounting_still_incomplete_after_the_last_attempt_fails_the_unit(
    tmp_path: Path,
) -> None:
    """A unit that cannot complete its own accounting after being told what
    is missing fails, with those problems on its record."""
    from tests.factories import activate_with

    activate_with(limits={"max_adapt_rounds": 2})
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    always_incomplete = json.dumps({"tests": [{"name": "test_click", "decision": "keep"}]})
    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={
            "branch_commits": lambda cwd, base: 2,
            "restack_onto": lambda **kw: _restacked(
                conflict="x", old_tests=("test_click", "test_console")
            ),
            "reset_to": lambda tree, onto, keep: None,
            "tests_in": lambda tree: {"test_click"},
            "tests_changed": lambda tree, ref: set(),
            "run_rework": (
                lambda prompt, *, cwd: recorder.prompts.append(prompt) or always_incomplete
            ),
        }
    )

    outcome = runner.run(unit(), base="spec/c/2", graph=[])

    assert outcome.status == "failed"
    assert len(recorder.prompts) == 2, "asked again up to the bound, then stopped"
    assert "no decision for `test_console`" in store.get(unit().id).feedback
    assert "push" not in recorder.events


def test_a_changed_test_answered_keep_is_asked_again(tmp_path: Path) -> None:
    """The pipeline measured `test_click` as different from the old work, so
    the agent saying it is unchanged does not stand."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    answers = [
        json.dumps({"tests": [{"name": "test_click", "decision": "keep"}]}),
        json.dumps(
            {
                "tests": [
                    {
                        "name": "test_click",
                        "decision": "adapt",
                        "reason": "dropped the console assertion to fit the new shape",
                    }
                ]
            }
        ),
    ]

    def run_rework(prompt: str, *, cwd: Path) -> str:
        recorder.prompts.append(prompt)
        return answers[len(recorder.prompts) - 1]

    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={
            "branch_commits": lambda cwd, base: 2,
            "restack_onto": lambda **kw: _restacked(conflict="x", old_tests=("test_click",)),
            "reset_to": lambda tree, onto, keep: None,
            "tests_in": lambda tree: {"test_click"},
            "tests_changed": lambda tree, ref: {"test_click"},
            "run_rework": run_rework,
        }
    )

    outcome = runner.run(unit(), base="spec/c/2", graph=[])

    assert outcome.status == "open"
    assert "test_click" in recorder.prompts[1]
    assert "differs from the previous work" in recorder.prompts[1]


def test_follow_up_decisions_are_merged_over_the_first_answers(tmp_path: Path) -> None:
    """An agent that only answers for the tests just named must not lose the
    decisions it already gave."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()

    def retire(name: str) -> str:
        return json.dumps(
            {
                "tests": [
                    {
                        "name": name,
                        "decision": "retire",
                        "reason": "the predecessor made console capture opt-in, so this is moot",
                    }
                ]
            }
        )

    answers = [retire("test_click"), retire("test_console")]

    def run_rework(prompt: str, *, cwd: Path) -> str:
        recorder.prompts.append(prompt)
        return answers[len(recorder.prompts) - 1]

    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={
            "branch_commits": lambda cwd, base: 2,
            "restack_onto": lambda **kw: _restacked(
                conflict="x", old_tests=("test_click", "test_console")
            ),
            "reset_to": lambda tree, onto, keep: None,
            "tests_in": lambda tree: set(),
            "tests_changed": lambda tree, ref: set(),
            "run_rework": run_rework,
        }
    )

    outcome = runner.run(unit(), base="spec/c/2", graph=[])

    assert outcome.status == "open"


def test_a_later_review_sees_what_earlier_rounds_asked_and_what_was_done(
    tmp_path: Path,
) -> None:
    """Without it each round starts over: reviews find new, neighbouring
    problems every round, with no way to check the last ones were met or to
    know what was settled."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    recorder.verdicts = [
        '{"approved": false, "feedback": "fill times out on long text"}',
        '{"approved": true, "feedback": ""}',
    ]
    runner = make_runner(store, recorder, tmp_path).model_copy(
        update={"run_rework": lambda prompt, *, cwd: "Scaled the timeout with text length."}
    )

    runner.run(unit(), base="main", graph=[])

    assert "The builder's response" not in recorder.contexts[0], "the first review has no history"
    later = recorder.contexts[1]
    assert "round 2 of the loop" in later
    assert "fill times out on long text" in later
    assert "Scaled the timeout with text length." in later
    assert "Do not re-open points that are settled" in later
    assert store.get(unit().id).review_rounds == (), "cleared once in review"


def test_the_loop_s_history_survives_a_pause(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    recorder.verdicts = ['{"approved": false, "feedback": "sweep the other tools"}']
    runner = make_runner(store, recorder, tmp_path).model_copy(update={"may_start": Gate(3)})

    assert runner.run(unit(), base="main", graph=[]).status == "paused"
    assert store.get(unit().id).review_rounds[0]["asked"] == "sweep the other tools"


def test_reviews_are_asked_to_sweep_and_to_say_what_done_looks_like() -> None:
    from agent_build_kit.pipeline.stack_runner import REVIEW_FEEDBACK_PROMPT
    from agent_build_kit.pipeline.wiring import REVIEW_PROMPT

    review, fix = " ".join(REVIEW_PROMPT.split()), " ".join(REVIEW_FEEDBACK_PROMPT.split())
    assert "Find everything in one pass" in review
    assert "Sweep the domain" in review
    assert "Say what done looks like" in review
    assert "look for others of the same kind" in fix
    assert "point by point" in fix


def test_reviews_check_that_tests_hold_the_code_to_the_real_system() -> None:
    """A change can pass every review with tests whose fakes encode the
    implementation's own assumptions: a fake counting a call as the effect
    the real one does not have, a fake returning plain values where the real
    API wraps them, hand-written events with none of the real system's
    metadata. All of those are bugs live, found in minutes by driving the
    real server."""
    from agent_build_kit.pipeline.wiring import REVIEW_PROMPT

    review = " ".join(REVIEW_PROMPT.split())
    assert "Check the tests against the real system" in review
    assert "would it still pass if the real" in review
    assert "protocol boundary" in review
    assert "recorded from the real system" in review


def test_test_writers_fake_at_the_boundary_and_record_real_fixtures() -> None:
    from agent_build_kit.pipeline.stack_runner import TESTS_PROMPT

    tests = " ".join(TESTS_PROMPT.split())
    assert "protocol boundary" in tests
    assert "recorded from the real system" in tests


def test_a_change_only_a_person_can_make_holds_the_unit_instead_of_spending_rounds(
    tmp_path: Path,
) -> None:
    """The reviewer asks for an edit to a file Claude Code protects from the
    builder, the builder says so, and the loop would spend its last rounds
    asking again before failing."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    recorder.verdicts = [
        '{"approved": false, "feedback": "exclude the file from check-yaml", "needs_human": true}'
    ]

    outcome = make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert outcome.status == "held"
    assert recorder.events.count("review") == 1, "no further rounds"
    assert "claude:rework" not in recorder.events
    assert store.get(unit().id).state == "held"
    assert store.get(unit().id).feedback == "exclude the file from check-yaml"


def test_needs_human_only_counts_alongside_a_rejection() -> None:
    from agent_build_kit.pipeline.stack_runner import parse_verdict

    assert parse_verdict('{"approved": false, "feedback": "x", "needs_human": true}').needs_human
    assert not parse_verdict('{"approved": false, "feedback": "x"}').needs_human
    assert not parse_verdict("not json").needs_human


class CountingGate(Gate):
    """`Gate`, but remembering how many times it was asked — so a test can
    tell "the same check, reused" from "one more read than the boundary
    pattern already makes"."""

    def __init__(self, yes: int) -> None:
        super().__init__(yes)
        self.calls = 0

    def __call__(self) -> tuple[bool, str]:
        self.calls += 1
        return super().__call__()


def test_an_empty_step_pauses_when_usage_is_exhausted(tmp_path: Path) -> None:
    """An agent told it is out of usage can finish a step cleanly having
    written nothing. Failed outright, that unit lands in the list a person
    has to read with no record of why. Told apart by the usage reading, it is
    paused instead — in the same shape a stop between steps already uses, so
    the graph, the note and the resume all need nothing new."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder(commits_from_impl=0)
    # Yes for the unit to start, yes before implement, no once implement ends
    # having written nothing — the window filled while it ran.
    runner = make_runner(store, recorder, tmp_path).model_copy(update={"may_start": Gate(2)})

    outcome = runner.run(unit(), base="main", graph=[])

    assert outcome.status == "paused"
    stored = store.get(unit().id)
    assert stored.state == PLANNED
    assert stored.resume_from == "implement"
    note = stored.history[-1].get("note", "")
    assert note.startswith("paused before implement")
    assert "75%" in note


def test_the_pause_check_costs_no_more_than_the_one_read_it_takes(tmp_path: Path) -> None:
    """The reading is the one already held: classifying an empty step must
    not turn into a poll. It costs exactly one read beyond the boundary
    checks a run to this point already makes — one to start the unit, one
    before implement, one to judge the empty result — never more, and never
    one taken while implement itself is running."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder(commits_from_impl=0)
    gate = CountingGate(2)
    runner = make_runner(store, recorder, tmp_path).model_copy(update={"may_start": gate})

    outcome = runner.run(unit(), base="main", graph=[])

    assert outcome.status == "paused"
    assert gate.calls == 3


def test_an_empty_step_is_not_a_pause_when_usage_is_healthy(tmp_path: Path) -> None:
    """Not every empty implementation step is a pause or a failure. The tests
    step still committed, so the branch carries this unit's own work even
    though the implementation added nothing on top of it — reviewed and
    pushed like any other unit, not judged as if nothing were there at all."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder(commits_from_impl=0)

    outcome = make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert outcome.status == "open"
    assert "review" in recorder.events
    stored = store.get(unit().id)
    assert stored.resume_from != IMPLEMENT
    assert stored.state != PLANNED


def test_a_usage_paused_empty_step_is_drawn_as_paused_and_resumes_with_its_commits_intact(
    tmp_path: Path,
) -> None:
    """Reusing the boundary-pause shape means the graph and the resume the
    pause schedules need nothing new: a `planned` unit carrying this note is
    already what both already handle. The resume picks up at implement, the
    step that did not finish, with the tests commit from before the pause
    still on the branch."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    first_run = Recorder(commits_from_impl=0)
    runner = make_runner(store, first_run, tmp_path).model_copy(update={"may_start": Gate(2)})

    outcome = runner.run(unit(), base="main", graph=[])
    assert outcome.status == "paused"

    diagram = render_mermaid([store.get(unit().id)])
    assert "paused_usage" in diagram
    assert "paused: usage" in diagram

    second_run = Recorder(commits_from_impl=1)
    second_run.made = 1  # the tests commit from before the pause is still there
    resumed = make_runner(store, second_run, tmp_path).run(unit(), base="main", graph=[])

    assert "claude:tests" not in second_run.events, "the tests commit survived the pause"
    assert second_run.events[0] == "claude:impl"
    assert resumed.status == "open"
