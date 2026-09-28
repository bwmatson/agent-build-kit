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
from pathlib import Path

import pytest

from agent_build_kit.pipeline.stack_runner import Restacked, UnitRunner
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, branch_name
from tests.factories import unit


class Recorder:
    """Stands in for every side effect, recording what happened in order."""

    tier1_output: str = ""

    def __init__(self, *, commits_from_impl: int = 1, tier2_ok: bool = True, tier1_ok: bool = True):
        self.events: list[str] = []
        self.prompts: list[str] = []
        self.commits_from_impl = commits_from_impl
        self.tier2_ok = tier2_ok
        self.tier1_ok = tier1_ok
        self.pushed_shas: list[str] = []

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

    def tier1(self, *, cwd: Path, base: str = "main") -> tuple[bool, str]:
        self.events.append("tier1")
        return self.tier1_ok, self.tier1_output

    def tier2(self, *, cwd: Path) -> tuple[bool, str]:
        self.events.append("tier2")
        return self.tier2_ok, "## Tier 2 results\nfine"

    def push(self, branch: str, *, cwd: Path) -> str:
        self.events.append("push")
        self.pushed_shas.append("abc123")
        return "abc123"

    def open_pr(self, unit, *, body: str, base: str, cwd: Path) -> int:
        self.events.append("pr")
        return 7

    def post_status(self, sha: str, ok: bool) -> None:
        self.events.append("status")


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

    runner(recorder).run(unit(), base="main", graph=[])

    assert "review" not in recorder.events


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
    """The original guard has to survive: a run that wrote nothing, on a branch
    with nothing, is a failure and not a resume."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder(commits_from_impl=0)
    runner = make_runner(store, recorder, tmp_path)
    runner.branch_commits = lambda cwd, base: 0

    assert runner.run(unit(), base="main", graph=[]).status == "failed"


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

    def tier1_that_commits(*, cwd: Path, base: str = "main") -> tuple[bool, str]:
        recorder.made += 1
        return original_tier1(cwd=cwd, base=base)

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


def test_the_loop_is_bounded(tmp_path: Path) -> None:
    """A reviewer that never approves would otherwise spend the window until
    the usage guard stopped it, on one unit."""
    from agent_build_kit.config import active

    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    recorder.verdicts = [rejecting("still no")] * 20

    outcome = make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert outcome.status == "failed"
    assert recorder.events.count("review") == active().limits.max_review_rounds
    assert "tier1" not in recorder.events, "an unapproved branch is not verified or pushed"


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
    Reading it as approval would make a broken reviewer invisible."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    recorder.verdicts = ["I think it looks fine, honestly"] * 20

    assert (
        make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[]).status == "failed"
    )


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
    """Nothing would review it: the unit fails either way, having paid for a
    rework nobody sees."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder()
    recorder.verdicts = ['{"approved": false, "feedback": "no"}'] * 3

    outcome = make_runner(store, recorder, tmp_path).run(unit(), base="main", graph=[])

    assert outcome.status == "failed"
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

    def review(*, cwd: Path) -> str:
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
            "run_review": lambda *, cwd: used.append("standard") or recorder.review(cwd=cwd),
            "run_rework_review": lambda *, cwd: used.append("rework") or recorder.review(cwd=cwd),
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

    def review(*, cwd: Path) -> str:
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

    def open_pr(u, *, body: str, base: str, cwd: Path) -> int:
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

    assert recorder.contexts[0] == "", "the first review has no history"
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
    from agent_build_kit.pipeline.stack_runner import needs_human

    assert needs_human('{"approved": false, "feedback": "x", "needs_human": true}')
    assert not needs_human('{"approved": false, "feedback": "x"}')
    assert not needs_human("not json")
