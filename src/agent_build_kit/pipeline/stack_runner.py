"""Driving one unit from planned to an open PR.

Every other module contributes a piece; this one puts them in order, and the
order is the guarantee (docs/architecture.md):

1. **Ask the usage guard first.** It gates *starting* work, so the refusal has
   to come before the worktree and before the first expensive call — never
   halfway through, which would leave a unit half-committed.
2. **Tests, commit, implementation, commit.** Two scoped runs, because
   OpenSpec has no hook between tasks and the separate tests commit is the
   only evidence the tests ever failed.
3. **Review, but only if there were commits.** Reviewing an empty branch
   spends a model call to say nothing.
4. **Tier 1, then tier 2.** In that order: no point occupying the single local
   stack to re-confirm a failure tier 1 already found.
5. **Push, then post the status.** GitHub only accepts a status for a commit
   it already has.
6. **Record the outcome.** A failed unit is marked failed rather than left
   looking planned, or the next round picks it up and redoes the same work.

Side effects arrive as callables. That keeps the sequence testable in
milliseconds, and keeps this module about ordering rather than about the
mechanics of git, gh and Claude.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from agent_build_kit.config import active, models
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.pr_body import build_pr_body
from agent_build_kit.pipeline.pr_replies import last_json
from agent_build_kit.pipeline.task_progress import mark_groups
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import (
    HELD,
    IN_REVIEW,
    PLANNED,
    SATISFIED,
    Unit,
    branch_name,
    later_groups,
    local_ref,
)
from agent_build_kit.runtimes.base import AgentInterrupted, AgentRateLimited

# Where a unit stopped between steps, so its resume starts there. See
# `checkpoint` in `StackRunner.run`. Also recorded as each step starts, so a
# run killed inside one resumes at it.
TESTS = "tests"
IMPLEMENT = "implement"
REVIEW = "review"
# A review of rework, which has its own model (models().rework_review).
# Recorded apart from REVIEW so a unit resumed there is judged by the right one:
# the flag that said "this follows a rework" is the feedback, which a resume no
# longer carries.
REWORK_REVIEW = "rework_review"
REWORK = "rework"
VERIFY = "verify"

# The change lives in the planning repo, which the run can read because
# `build_run_claude` passes `--add-dir`. Named by path rather than driven by
# `/opsx:apply`: that command exists only where OpenSpec is installed, which
# is the planning repo, while the unit is built in the target repo's worktree.
CHANGE_DIR = "{planning_repo}/openspec/changes/{change}"

TESTS_PROMPT = """\
The change you are implementing is specified in {change_dir} — read its
tasks.md, proposal.md, design.md and specs/ before you start.

Work ONLY the test tasks of task group(s) {groups}, which are tagged for this
repo. Write the tests the group's acceptance criteria call for, and stop.
{boundary}
You may add stubs for code that does not exist yet — a signature whose body is
only `raise NotImplementedError`, or a model field — so the tests fail when
they run instead of failing to import. Stubs contain no logic.

Where a test needs a stand-in for something outside this code (a library, a
browser, a service), fake it at the protocol boundary — the raw shape the real
system sends (CDP JSON, an HTTP body, a CLI's output) — not in place of a
third-party wrapper, whose behaviour is part of what is being tested. Give a
parser of external data fixtures recorded from the real system, or carrying
everything the real one does (metadata, nulls, empty values), not only the
fields the code will read.

Before you finish: run linting and formatting, which must pass, and run the
new tests, which must fail. A test that passes now is not testing the
behaviour this group adds. Do not write the implementation.
The change's files are read-only for you: do not tick boxes in its tasks.md
or edit anything under {change_dir}. The pipeline records a task as done once
the unit has passed review, tier 1 and been pushed.
"""

REVIEW_FEEDBACK_PROMPT = """\
A review of this branch asked for changes, for change {change_dir}, task
group(s) {groups}:

---
{feedback}
---

Address it. The reviewer reads the branch but does not edit it, so nothing here
is fixed unless you fix it. Fix every instance it names, and look for others of
the same kind — the same pattern in sibling tools, callers or code paths — so
the next round does not find them. Beyond that, keep the change to what was
asked for.

Finish with a short account, point by point: what you did, or why you did not.
The next reviewer is shown it alongside this feedback, so a point you disagree
with gets judged on your reason rather than read as an oversight.

If a change cannot be made because your environment refuses it — a file Claude
Code protects, a permission you do not have — do not work around it. Mark that
point `BLOCKED:` in your account, with the exact change a person should make.

Run linting, formatting, types and the tests before you finish.
The change's files are read-only for you: do not tick boxes in its tasks.md
or edit anything under {change_dir}. The pipeline records a task as done once
the unit has passed review, tier 1 and been pushed.
"""


def needs_human(output: str) -> bool:
    """Whether a rejecting reviewer says only a person can make what is left.

    Read apart from `parse_verdict`, and only ever acted on alongside a
    rejection: an unreadable reply is still just an unreadable reply.
    """
    match = re.search(r"\{.*\}", output, re.DOTALL)
    if not match:
        return False
    try:
        return bool(json.loads(match.group(0)).get("needs_human"))
    except (ValueError, AttributeError):
        return False


def parse_verdict(output: str) -> tuple[bool, str]:
    """(approved, what to fix) from a reviewer's reply.

    An unreadable reply is not an approval. Reading it as one would make a
    reviewer that had stopped answering properly invisible — the branch would
    sail through on a parse failure, which is the one outcome worse than a
    reviewer that rejects everything.
    """
    match = re.search(r"\{.*\}", output, re.DOTALL)
    if not match:
        return False, "the reviewer's reply was not readable as a verdict"
    try:
        payload = json.loads(match.group(0))
    except ValueError:
        return False, "the reviewer's reply was not readable as a verdict"
    return bool(payload.get("approved")), str(payload.get("feedback") or "").strip()


REWORK_PROMPT = """\
Review asked for a change to the work already on this branch, specified at
{change_dir}, task group(s) {groups}. This is PR #{pr}.

---
{feedback}
---

Address what was **meant**, not only what was written. Review comments are
written quickly against a diff, and a reviewer can be wrong in a way the code
cannot be: a suggestion may name the wrong mechanism, assume a default that
does not hold, or ask for something that would break the thing it is trying to
improve. Work out the intent and satisfy that.

Where the literal suggestion would be wrong, do the right thing and say why in
your reply to that comment. Where you genuinely cannot tell what was intended,
implement nothing for that point and ask in your reply, rather than guessing at
a rewrite. A question gets an answer, whether or not it also gets a change.

The tests and implementation are already here and were green when this branch
was pushed, so this is an edit to existing work, not a fresh start. Change a
test only where the feedback is about the test itself.

Run linting, formatting, types and the tests before you finish.

Do not post to GitHub yourself. Finish with JSON and nothing after it; the
pipeline posts it once your work is pushed, so it can describe the code as the
reviewer will see it:

{{"replies": [{{"comment_id": <N from a "[comment N]" line>, "body": "..."}}],
 "summary": "..."}}

One reply per `[comment N]` you changed something for or answered: what you
did, or your answer, in a sentence or two — not a restatement of the comment.
`summary` is for feedback with no comment id (a review's overall text) or a
point that spans several comments; leave it empty otherwise.

Write them for the reviewer reading the pushed PR. Say what changed in the
code and why, or answer the question. Leave out whether anything is committed
or pushed — by the time they are read it is, and each reply is signed with the
commit it describes — and leave out your own verification (lint, types, test
counts); tier 1 runs before anything is pushed.
The change's files are read-only for you: do not tick boxes in its tasks.md
or edit anything under {change_dir}. The pipeline records a task as done once
the unit has passed review, tier 1 and been pushed.
"""

IMPLEMENTATION_PROMPT = """\
Work the remaining tasks of task group(s) {groups} in the change specified at
{change_dir}, and stop before any later group.
{boundary}
Make the tests written in the previous commit pass, keeping the change to what
those tests require. Do not weaken or delete a test to make it pass. Run
linting, formatting, types and the tests before you finish.
The change's files are read-only for you: do not tick boxes in its tasks.md
or edit anything under {change_dir}. The pipeline records a task as done once
the unit has passed review, tier 1 and been pushed.
"""

# Given to the build prompts above, only when this change has units after this
# one: naming what belongs to them is what stops a capable agent finishing
# that work too, once it notices the next group is one edit away.
BUILD_BOUNDARY_NOTE = """
Task group(s) {later} belong to later units of this change, each its own pull
request. Leave them alone even where their code looks one edit away: pulling
that work forward makes this pull request bigger than the plan intended, and
leaves the change's record of what is done crediting the wrong unit.
"""

# Given to the reviewer alongside the build boundary above: the same groups,
# so a finding whose fix belongs there is reported rather than required.
REVIEW_BOUNDARY_NOTE = """**Task group(s) {later} belong to later units of this change.** A finding
whose fix is only there does not block this review — report it as belonging
to a later unit, not required of this one.
"""


class Restacked(Frozen):
    """What moving a unit onto its updated predecessor did.

    Three outcomes, each handled differently by the runner:

    - applied cleanly (`resolved` empty, no `conflict`): the unit's own change
      is what it was. If review had approved it, the approval carries over.
    - applied with a resolver (`resolved` names the files): code no review has
      seen, on top of a predecessor that changed — reviewed, with the reviewer
      asked to check the unit's tests still fit.
    - could not be applied (`conflict`): the adapt step ports the work by hand
      and accounts for every one of the unit's previous tests.
    """

    onto_unit: str
    onto_intent: str
    old_base: str
    old_head: str
    resolved: tuple[str, ...] = ()
    conflict: str = ""
    # Tests the unit's previous work added or changed, for the adapt step to
    # account for. Only filled in when there is a conflict.
    old_tests: tuple[str, ...] = ()


class PortedTest(Frozen):
    name: str
    decision: str  # keep | adapt | retire
    reason: str = ""


ADAPT_PROMPT = """This unit — change {change_dir}, task group(s) {groups} — was built on an
earlier version of `{onto_unit}` ({onto_intent}). That predecessor has changed
since, and replaying this unit's commits onto its new version conflicted beyond
what could be merged mechanically:

{conflict}

So this branch has been reset to the new base, and the previous work kept at
`{old_ref}`. Its own changes are `git diff {old_base} {old_ref}`; what it was
built on is `{old_base}`.

Port this unit's work onto the new base. The predecessor as it is now is
authoritative: adapt to its current shape rather than restoring what it
replaced, and do not re-implement anything it already provides.

These are the tests the previous work added or changed:

{tests}

Decide each one before carrying it over:

- **keep** — still meaningful against the new base; carried over unchanged.
- **adapt** — still meaningful, but changed to fit the predecessor's new shape.
  Say what changed.
- **retire** — no longer meaningful, because of a specific change in the
  predecessor. Name the change. "It fails" or "it was hard to port" is not a
  reason: a test that still describes behaviour this unit's tasks require is
  kept or adapted, whatever it takes.

Write any test the tasks require that the previous work did not have. Run
linting, formatting, types and the tests before you finish.

The change's files are read-only for you: do not tick boxes in its tasks.md
or edit anything under {change_dir}.

Finish with JSON and nothing after it:

{{"tests": [{{"name": "<test name>", "decision": "keep|adapt|retire",
             "reason": "..."}}],
 "summary": "what changed in porting, for the reviewer"}}
"""

# Given to a review that follows a rework in the same loop.
EARLIER_ROUNDS_NOTE = """\
**Earlier rounds of this review.** This is round {round} of the loop. What the
earlier rounds asked for, and what the builder said it did about each:

{rounds}

Check first that each point was done, or that the builder's reason for not
doing it holds. Do not re-open points that are settled. Raise new problems
only in what the reworks changed, or ones genuinely missed before — and for
those, say why they were not visible earlier.
"""

# Given to the reviewer of a branch that was moved onto a changed predecessor.
PREDECESSOR_NOTE = """**This branch was moved onto an updated predecessor.** `{onto_unit}` changed
after this unit was built on it, and {how}.

Before anything else, check each of this unit's tests against the predecessor
as it is now. Is it still meaningful? Does it assert behaviour the predecessor
removed or reshaped, or duplicate coverage the predecessor now provides? Is a
test the tasks require missing? {decisions}Report any test that no longer
belongs, or any change to the tests that was not justified, as a required
change — a test that passes against the wrong behaviour is worse than none.
"""


# Enough of each round for the reviewer to check it against, without one long
# round crowding out the rest of the prompt.
ROUND_CHARS = 4000


def _earlier_rounds(rounds: Sequence[dict]) -> str:
    if not rounds:
        return ""
    parts = []
    for number, entry in enumerate(rounds, start=1):
        asked = str(entry.get("asked", "")).strip()[:ROUND_CHARS]
        response = str(entry.get("response", "")).strip()[:ROUND_CHARS] or "(no account given)"
        parts.append(f"Round {number} asked:\n{asked}\n\nThe builder's response:\n{response}")
    return EARLIER_ROUNDS_NOTE.format(round=len(rounds) + 1, rounds="\n\n---\n\n".join(parts))


def _no_reset() -> None:
    raise RuntimeError("this runner was not given a way to reset a branch")


def parse_test_decisions(answer: str) -> list[PortedTest]:
    value = last_json(answer, {"tests"}) or {}
    out: list[PortedTest] = []
    for item in value.get("tests") or []:
        try:
            out.append(PortedTest.model_validate(item))
        except ValueError:
            continue
    return out


def check_test_decisions(
    old_tests: Sequence[str], decisions: Sequence[PortedTest], present: set[str]
) -> list[str]:
    """What is wrong with how the adapt step accounted for the unit's tests.

    A test that silently vanished is the thing this exists to catch: a port
    can make a conflict disappear by dropping what it could not carry over.
    """
    problems: list[str] = []
    decided = {d.name: d for d in decisions}
    for name in old_tests:
        decision = decided.get(name)
        if decision is None:
            problems.append(f"no decision for `{name}`")
        elif decision.decision not in ("keep", "adapt", "retire"):
            problems.append(f"`{name}`: unknown decision {decision.decision!r}")
        elif decision.decision == "retire" and len(decision.reason.strip()) < 20:
            problems.append(f"`{name}` retired without a reason naming the predecessor's change")
        elif decision.decision == "keep" and name not in present:
            problems.append(f"`{name}` is marked keep but is not in the tree")
        elif (
            decision.decision == "adapt"
            and name not in present
            and not any(test in decision.reason for test in present)
        ):
            problems.append(
                f"`{name}` is marked adapt but neither it nor a renamed test is present"
            )
    return problems


class RunOutcome(Frozen):
    status: str  # "open" | "paused" | "held" | "satisfied" | "failed"
    detail: str
    pr: int | None = None


class UnitRunner(BaseModel):
    """Runs one unit, given the ways to do each step.

    `arbitrary_types_allowed` because `UnitStore` is a plain class rather than
    a model — it owns a file, not a value — and pydantic has no schema for it.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    store: UnitStore
    planning_repo: Path
    worktree: Callable[[Unit, str], Path]
    may_start: Callable[[], tuple[bool, str]]
    run_claude: Callable[..., str]
    run_rework: Callable[..., str]
    run_review: Callable[..., str]
    run_rework_review: Callable[..., str]
    commit: Callable[..., int]
    branch_commits: Callable[..., int]
    upstream_incomplete: Callable[..., str]
    # Why the base this run started on is no longer the unit's base — a
    # parent merged, or was restacked, while it built — or "". Given the
    # worktree and the base's tip when the run set it up (`base_tip`). See
    # `wiring.build_base_moved`.
    base_moved: Callable[..., str] = lambda unit, base, **kwargs: ""
    base_tip: Callable[[Path, str], str] = lambda tree, ref: ""
    restack_onto: Callable[..., Restacked | None]
    run_tier1: Callable[..., tuple[bool, str]]
    run_tier2: Callable[..., tuple[bool, str]]
    push: Callable[..., str]
    open_pr: Callable[..., int]
    post_status: Callable[[str, bool], None]
    # Posts a rework's replies to the review threads it answered, after the
    # push. See `pr_replies`.
    reply: Callable[..., None] = lambda **kwargs: None
    # The worktree's HEAD. Required, with no default: a stand-in that always
    # answered "" would match an unset approval and wave every push through.
    head: Callable[[Path], str]
    # For the adapt step: put the branch on a new base keeping the old work
    # under a ref, and list the tests the worktree has.
    reset_to: Callable[[Path, str, str], None] = lambda tree, onto, keep: _no_reset()
    tests_in: Callable[[Path], set[str]] = lambda tree: set()
    # Each step as it starts and how it ended, so the tick log says where a
    # unit has got to rather than going quiet for the length of a build.
    log: Callable[[str], None] = lambda message: None

    def run(self, unit: Unit, *, base: str, graph: list[StoredUnit]) -> RunOutcome:
        allowed, why = self.may_start()
        if not allowed:
            # Before anything else: pausing here costs nothing, while pausing
            # after the first run leaves a worktree and a half-built unit.
            return RunOutcome(status="paused", detail=why)

        branch = branch_name(unit)
        groups = ", ".join(str(group) for group in unit.groups)
        later = ", ".join(str(group) for group in later_groups(unit, graph))
        build_boundary = BUILD_BOUNDARY_NOTE.format(later=later) if later else ""
        review_boundary = REVIEW_BOUNDARY_NOTE.format(later=later) if later else ""
        # From the store, not the passed-in unit: `run` takes a `Unit`, and
        # the store is what the poller wrote the review's words to.
        feedback = self.store.get(unit.id).feedback
        change_dir = CHANGE_DIR.format(planning_repo=self.planning_repo, change=unit.change)
        self.store.set_state(unit.id, "running", branch=branch)
        ref = local_ref(base)
        tree = self.worktree(unit, ref)
        # The tip of the base this build is placed on, taken before the
        # restack or adapt below so that a rewrite during them is caught too:
        # an adapt runs a model for minutes, and a parent restacked meanwhile
        # keeps its branch name and rewrites its commits, which only a
        # comparison against this can see. A base that moves before the
        # restack costs one needless hold; the resume records it again.
        start = self.base_tip(tree, ref)

        existing = self.branch_commits(tree, ref)
        self.log(
            f"on {base}, {existing} commit(s) already on the branch"
            + (", with feedback to address" if feedback else "")
        )

        if existing:
            # First, before reviewing, verifying or pushing. A unit held while
            # its parent was reworked comes back to a base that was force-pushed
            # underneath it, so its branch no longer contains the commits it sits
            # on. Judging it against that base would judge work it does not have.
            try:
                restacked = self.restack_onto(tree=tree, branch=branch, base=ref, unit=unit)
            except (AgentRateLimited, AgentInterrupted):
                # The resolver could not run, which says nothing about the
                # branch: the tick pauses or reclaims, and the unit is not failed.
                raise
            except Exception as error:  # noqa: BLE001
                # `move_branch_onto` resolves what it can and raises otherwise.
                # Carrying on would verify a half-rebased branch.
                why = f"restack onto {base} conflicted: {error}"
                # Added to, not replacing: the feedback waiting may be a
                # review's, and replacing it would lose that review.
                waiting = self.store.get(unit.id).feedback
                self.store.set_feedback(unit.id, f"{waiting}\n\n{why}".strip())
                return self._fail(unit, why)

            if restacked is not None:
                if restacked.conflict:
                    if outcome := self._adapt(unit, tree, ref, restacked, groups, change_dir):
                        return outcome
                elif restacked.resolved:
                    files = ", ".join(restacked.resolved)
                    self.log(f"restacked onto {base}, resolving {files}; review checks the tests")
                    self.store.set_predecessor_note(
                        unit.id,
                        PREDECESSOR_NOTE.format(
                            onto_unit=restacked.onto_unit,
                            how=f"moving onto it needed conflict resolution in {files}",
                            decisions="",
                        ),
                    )
                else:
                    self.log(f"restacked onto {base} cleanly")
                existing = self.branch_commits(tree, ref)

        resume = self.store.get(unit.id).resume_from
        # Set only on the fresh-build path below, when neither step added a
        # commit: the branch is exactly as it was, so there is nothing to
        # review or push, only tier 1 to judge it by.
        produced_nothing = False

        def pause(next_step: str, why: str) -> RunOutcome:
            self.log(f"paused before {next_step}: {why}")
            self.store.set_state(
                unit.id,
                PLANNED,
                note=f"paused before {next_step}: {why}",
                resume_from=next_step,
            )
            return RunOutcome(status="paused", detail=why)

        def checkpoint(next_step: str, *, usage: bool = True) -> RunOutcome | None:
            """Stop before `next_step` if the unit should not go on yet.

            Between steps, never mid-step: abandoning a step throws away what
            it produced, and every step ends in a commit. Three reasons to stop:

            - Something upstream went back for rework. Back to `planned`, which
              the dependency check already gates on, so the unit resumes by
              itself once the upstream is through review again.
            - The base moved: a parent merged while this built, or was
              restacked and so rewritten under the same name. The merge leaves
              a building branch alone rather than rebase the tree in use, so
              it is moved here instead — the resume's restack puts it on its
              new base before anything reaches a PR.
            - The usage window filled. A unit loops — build, review, rework,
              review again — and checking only when it started let one run on
              for hours past the threshold.

            `next_step` is recorded, and the resume starts exactly there. It
            used to be inferred from the branch, and a unit held after its
            build came back to commits and no feedback, read that as finished
            work, and skipped its review.
            """
            if why := self.upstream_incomplete(unit) or self.base_moved(
                unit, base, tree=tree, start=start
            ):
                self.log(f"held before {next_step}: {why}")
                self.store.set_state(
                    unit.id, PLANNED, note=f"held before {next_step}: {why}", resume_from=next_step
                )
                return RunOutcome(status="held", detail=f"held before {next_step} — {why}")
            if usage:
                allowed, why = self.may_start()
                if not allowed:
                    return pause(next_step, why)
            # Going ahead: record the step, so a run killed inside it resumes
            # there rather than guessing from the branch.
            self.store.record_step(unit.id, next_step)
            return None

        if resume in (REVIEW, REWORK_REVIEW, VERIFY):
            # Before the feedback check: a unit stopped after its rework still
            # carries that feedback, and addressing it again would redo work
            # that is already on the branch.
            self.log(f"resuming before {resume}")
            needs_review = resume in (REVIEW, REWORK_REVIEW)
        elif resume == REWORK and feedback:
            # Stopped between a review and its rework: this feedback is the
            # reviewer's (the review loop saved it before stopping), not the
            # PR's. So the review-feedback prompt, and nothing is posted — a
            # reply meant for the loop's own reviewer, posted to the PR,
            # addressed the human as "you asked" for things they never did.
            self.log(f"step: address the review it stopped before ({models().rework})")
            response = self.run_rework(
                REVIEW_FEEDBACK_PROMPT.format(
                    change_dir=change_dir, groups=groups, feedback=feedback
                ),
                cwd=tree,
            )
            self._record_response(unit, response)
            self.commit(f"fix: {unit.title} (review, resumed)", cwd=tree)
            needs_review = True
        elif feedback:
            # One run, not the usual pair. The tests and implementation are
            # already on the branch and were green when it was pushed, so
            # re-running the tests step would write tests that exist and the
            # implementation prompt knows nothing of what was objected to.
            # Its own call, on the review model: deciding what a reviewer
            # meant is judgement work, and it only ran on the implementation
            # model because it shared `run_claude`'s plumbing.
            self.log(f"step: rework from feedback ({models().rework})")
            answer = self.run_rework(
                REWORK_PROMPT.format(
                    groups=groups,
                    change_dir=change_dir,
                    feedback=feedback,
                    pr=self.store.get(unit.id).pr or "(not yet opened)",
                ),
                cwd=tree,
            )
            self.commit(f"fix: {unit.title}", cwd=tree)
            if answer and self.store.get(unit.id).pr:
                # Only an existing PR has a reviewer waiting in its threads.
                pending = self.store.get(unit.id).pending_replies
                self.store.set_pending_replies(unit.id, (*pending, answer))
            # Always reviewed, whether or not the pipeline's commit found
            # anything: the agent may have committed itself, and the branch
            # may carry work no review has passed: a rework's own commit, on
            # top of rounds its review had rejected, would otherwise go to the
            # PR unreviewed.
            needs_review = True
        elif existing and resume not in (TESTS, IMPLEMENT):
            # Nothing to build: the branch already carries this unit's work and
            # review has asked for nothing. Unit 2 spent twelve minutes
            # re-running both prompts to rebuild a branch it had already
            # produced, because the runner only discovered there was nothing to
            # do after paying for both. Reviewed below unless review already
            # approved exactly this commit.
            needs_review = False
        else:
            if resume != IMPLEMENT:
                self.store.record_step(unit.id, TESTS)
                self.log(f"step: write the tests ({models().implement})")
                self.run_claude(
                    TESTS_PROMPT.format(
                        groups=groups, change_dir=change_dir, boundary=build_boundary
                    ),
                    cwd=tree,
                )
                self.commit(f"test: {unit.title}", cwd=tree)
                if outcome := checkpoint(IMPLEMENT):
                    return outcome

            self.log(f"step: implement ({models().implement})")
            before = self.branch_commits(tree, ref)
            self.run_claude(
                IMPLEMENTATION_PROMPT.format(
                    groups=groups, change_dir=change_dir, boundary=build_boundary
                ),
                cwd=tree,
            )
            self.commit(f"feat: {unit.title}", cwd=tree)
            # Counted on the branch, not taken from the commit step: an agent
            # that commits its own work leaves the pipeline nothing to commit,
            # which read as the run having produced nothing. And a diff from
            # the tests step alone is still this unit's own work — reviewed,
            # not treated as empty just because the implementation added
            # nothing on top of it.
            after = self.branch_commits(tree, ref)
            if after == before:
                # An agent told it is out of usage can finish a step cleanly
                # having written nothing. Told apart here by the same reading
                # `checkpoint` already takes at each boundary, that is a pause
                # rather than a failure — the same shape a stop between steps
                # already uses.
                allowed, why = self.may_start()
                if not allowed:
                    return pause(IMPLEMENT, why)
                # Empty for any other reason is not judged by counting commits
                # here: what is on the branch is reviewed, and tier 1 below
                # judges a branch with nothing on it at all.
            needs_review = after > 0
            produced_nothing = not needs_review

        if (
            not needs_review
            and not produced_nothing
            and self.head(tree) != self.store.get(unit.id).approved
        ):
            # Whatever the path here, nothing reaches the PR that the review
            # loop has not approved at this exact commit — a restack that
            # rewrote the branch, or work from a run that stopped before its
            # verdict, is reviewed like anything else. Not for a branch with
            # nothing on it at all: there is nothing there for a review to
            # read either.
            self.log("the branch is not the commit review approved; reviewing it")
            needs_review = True

        if needs_review:
            # The reviewer reports and the builder fixes, alternating until the
            # reviewer is satisfied. It used to edit the branch itself, which
            # put judgement and authorship in one place and discarded anything
            # it could only say — a review concluding "this leaks under
            # concurrency" had no way to tell anyone.
            #
            # Before tier 1, because a review that changed code afterwards
            # would invalidate the run that verified it.
            approved, why = self._review_until_satisfied(
                unit,
                tree,
                change_dir,
                groups,
                bool(feedback)
                or resume in (REWORK, REWORK_REVIEW)
                or bool(self.store.get(unit.id).predecessor_note),
                checkpoint,
                review_boundary,
            )
            if isinstance(approved, RunOutcome):
                return approved
            if not approved:
                self.store.set_feedback(unit.id, why)
                return self._fail(unit, f"review did not approve the branch: {why}")

        # Tier 1 is not a Claude run, so only upstream can stop it here.
        if outcome := checkpoint(VERIFY, usage=False):
            return outcome

        self.log("step: tier 1")
        tier1_ok, tier1_output = self.run_tier1(cwd=tree, base=ref)
        self.log(f"tier 1 {'passed' if tier1_ok else 'failed'}")
        if not tier1_ok:
            # Kept, not thrown away. Both pilot units failed here and a retry
            # knew nothing about why, so it re-ran both expensive prompts and
            # rebuilt the same branch. Recorded as feedback, a retry is one
            # scoped run against the actual failure — the same path review
            # comments take.
            self.store.set_feedback(unit.id, f"tier 1 failed:\n{tier1_output}".strip())
            return self._fail(unit, "tier 1 failed")

        if produced_nothing:
            # Nothing of this unit's own on the branch, and what is already at
            # the tip passes — the work its groups called for arrived another
            # way. Judged here, on the branch and the checks, never on the
            # build step's own report: that is the same sentence a run that
            # wrote nothing and should have failed would also produce.
            self.log("nothing to add and tier 1 passes — satisfied")
            self.store.set_state(unit.id, SATISFIED, note="already implemented; tier 1 passed")
            mark_groups(self._tasks(unit), unit.groups, done=True)
            return RunOutcome(status="satisfied", detail="already implemented; tier 1 passed")

        snapshot = None
        if unit.tier == "tier2":
            self.log("step: tier 2")
            ok, snapshot = self.run_tier2(cwd=tree)
            self.log(f"tier 2 {'passed' if ok else 'failed'}")
            if not ok:
                # Kept, as tier 1's is: a tier 2 failure that leaves no trace
                # has to be reproduced by hand.
                waiting = self.store.get(unit.id).feedback
                self.store.set_feedback(unit.id, f"{waiting}\n\ntier 2 failed:\n{snapshot}".strip())
                return self._fail(unit, "tier 2 failed")

        # Last gate before anything leaves the machine: a push against a base
        # that has since moved puts the parent's old commits in this unit's diff.
        if outcome := checkpoint(VERIFY, usage=False):
            return outcome

        # The rule, checked where it matters rather than inferred from the path
        # taken: the PR only ever receives the commit the review loop approved.
        head, approved_sha = self.head(tree), self.store.get(unit.id).approved
        if not approved_sha or head != approved_sha:
            return self._fail(
                unit,
                f"refusing to push {head[:9] or '?'}: review approved "
                f"{approved_sha[:9] or 'nothing'} on this branch",
            )
        sha = self.push(branch, cwd=tree)
        self.log(f"pushed {branch} at {sha[:9]}")

        stored = self.store.get(unit.id)
        pr = self.open_pr(
            unit,
            body=build_pr_body(stored, graph=graph or [stored], base=base, tier2_snapshot=snapshot),
            base=base,
            cwd=tree,
        )

        # After the push, never before: a status for a commit GitHub has not
        # seen is rejected.
        if unit.tier == "tier2":
            self.post_status(sha, True)

        # Cleared only now, after the work is pushed and the PR updated. Left
        # in place, the next tick would rework the unit again for a comment it
        # has already answered, and keep doing so.
        # Every PR rework's replies since the last push, now that what they
        # describe is on the PR — including ones from a run that stopped
        # before it could push.
        for answer in stored.pending_replies:
            self.reply(repo=unit.repo, pr=pr, answer_text=answer, sha=sha)
        if stored.pending_replies:
            self.store.set_pending_replies(unit.id, ())

        if feedback:
            self.store.set_feedback(unit.id, "")

        self.store.set_state(unit.id, IN_REVIEW, pr=pr, resume_from="")
        if self.store.get(unit.id).predecessor_note:
            self.store.set_predecessor_note(unit.id, "")
        if self.store.get(unit.id).review_rounds:
            self.store.set_review_rounds(unit.id, ())
        # Done means through the loop, verified and pushed — so here, and not
        # when a build merely finished. See `task_progress`.
        mark_groups(self._tasks(unit), unit.groups, done=True)
        self.log(f"in review: PR #{pr}")
        return RunOutcome(status="open", detail=f"opened #{pr}", pr=pr)

    def _review_until_satisfied(
        self,
        unit: Unit,
        tree: Path,
        change_dir: str,
        groups: str,
        reworking: bool,
        checkpoint: Callable[[str], RunOutcome | None],
        review_boundary: str = "",
    ) -> tuple[bool | RunOutcome, str]:
        """Alternate review and rework until the reviewer approves, or give up.

        The first round reviews a freshly built branch; every round after
        reviews a rework, which is why the model differs between them.
        """
        why = ""
        if not reworking:
            # A fresh build starts a fresh loop; a resumed or reworking one
            # carries the rounds it had.
            self.store.set_review_rounds(unit.id, ())
        for round_number in range(active().limits.max_review_rounds):
            first = round_number == 0 and not reworking
            if outcome := checkpoint(REVIEW if first else REWORK_REVIEW):
                return outcome, why
            # Committed before the reviewer looks, so the verdict is on a commit
            # — the one recorded below, and the only one that may be pushed. It
            # used to be committed after approval, as "leftovers", which put an
            # unreviewed commit on top of the reviewed ones.
            self.commit(f"chore: {unit.title} (uncommitted work)", cwd=tree)
            model = models().review if first else models().rework_review
            self.log(f"step: review round {round_number + 1} ({model})")
            # A branch moved onto a changed predecessor tells its reviewer so,
            # with the instruction to check its tests still fit.
            stored = self.store.get(unit.id)
            notes = [
                review_boundary,
                stored.predecessor_note,
                _earlier_rounds(stored.review_rounds),
            ]
            text = "\n\n".join(n for n in notes if n)
            context = {"context": text} if text else {}
            verdict = (self.run_review if first else self.run_rework_review)(cwd=tree, **context)
            approved, why = parse_verdict(verdict)
            if approved:
                sha = self.head(tree)
                self.store.record_approval(unit.id, sha)
                self.log(f"review approved {sha[:9]}")
                return True, ""

            self.log(f"review asked for changes: {' '.join(why.split())[:300]}")
            rounds = self.store.get(unit.id).review_rounds
            self.store.set_review_rounds(unit.id, (*rounds, {"asked": why, "response": ""}))
            if needs_human(verdict):
                # What is left is something the builder's environment refuses
                # (an edit to a file Claude Code protects). Asking again spends
                # rounds on a change it can never make, so stop and wait.
                self.store.set_feedback(unit.id, why)
                self.store.set_state(unit.id, HELD, note=f"needs a human: {why[:300]}")
                self.log(f"needs a human — held: {' '.join(why.split())[:300]}")
                return RunOutcome(status="held", detail=f"needs a human: {why[:200]}"), why
            if round_number == active().limits.max_review_rounds - 1:
                # The last round's review is the verdict. A rework after it
                # would never be reviewed: minutes spent on one end with it
                # unpushed and unseen.
                break
            # Kept as feedback before stopping, so the resume addresses what
            # this round asked for instead of reviewing the same branch again.
            self.store.set_feedback(unit.id, why)
            if outcome := checkpoint(REWORK):
                return outcome, why
            self.log(f"step: address review round {round_number + 1} ({models().rework})")
            response = self.run_rework(
                REVIEW_FEEDBACK_PROMPT.format(change_dir=change_dir, groups=groups, feedback=why),
                cwd=tree,
            )
            self._record_response(unit, response)
            self.commit(f"fix: {unit.title} (review round {round_number + 1})", cwd=tree)
        return False, why

    def _record_response(self, unit: Unit, response: str) -> None:
        """The builder's account of the last round's ask, for the next review."""
        rounds = list(self.store.get(unit.id).review_rounds)
        if rounds:
            rounds[-1] = {**rounds[-1], "response": response}
            self.store.set_review_rounds(unit.id, rounds)

    def _adapt(
        self,
        unit: Unit,
        tree: Path,
        ref: str,
        restacked: Restacked,
        groups: str,
        change_dir: str,
    ) -> RunOutcome | None:
        """Port the unit onto a predecessor it could not be replayed onto.

        The branch is reset to the new base, the old work kept under a ref, and
        the rework model ports it — deciding, for each of the unit's previous
        tests, whether it still belongs. Those decisions are checked here (every
        test accounted for, every kept one present, every retirement given a
        reason), then handed to the reviewer, who judges them.
        """
        self.log(
            f"step: adapt onto {restacked.onto_unit} — the restack could not be merged "
            f"({models().rework})"
        )
        keep = f"refs/spec-driven/pre-adapt/{unit.id}"
        self.reset_to(tree, ref, keep)
        answer = self.run_rework(
            ADAPT_PROMPT.format(
                change_dir=change_dir,
                groups=groups,
                onto_unit=restacked.onto_unit,
                onto_intent=restacked.onto_intent,
                conflict=restacked.conflict[:2000],
                old_ref=keep,
                old_base=restacked.old_base,
                tests="\n".join(f"- `{name}`" for name in restacked.old_tests) or "- (none found)",
            ),
            cwd=tree,
        )
        self.commit(f"adapt: {unit.title} onto {restacked.onto_unit}", cwd=tree)

        decisions = parse_test_decisions(answer)
        problems = check_test_decisions(restacked.old_tests, decisions, self.tests_in(tree))
        if problems:
            why = "the adapt step did not account for its tests: " + "; ".join(problems)
            waiting = self.store.get(unit.id).feedback
            self.store.set_feedback(unit.id, f"{waiting}\n\n{why}".strip())
            return self._fail(unit, why)

        rendered = "".join(
            f"\n- `{d.name}`: {d.decision}" + (f" — {d.reason}" if d.reason else "")
            for d in decisions
        )
        self.store.set_predecessor_note(
            unit.id,
            PREDECESSOR_NOTE.format(
                onto_unit=restacked.onto_unit,
                how="replaying this unit onto it conflicted, so its work was ported onto the "
                "new version by hand",
                decisions=(
                    f"The port decided, for its previous tests:{rendered}\n\nJudge each "
                    "decision, retirements especially. "
                )
                if decisions
                else "",
            ),
        )
        counts = {k: sum(d.decision == k for d in decisions) for k in ("keep", "adapt", "retire")}
        self.log(
            f"adapted: {counts['keep']} kept, {counts['adapt']} adapted, {counts['retire']} retired"
        )
        return None

    def _tasks(self, unit: Unit) -> Path:
        change = CHANGE_DIR.format(planning_repo=self.planning_repo, change=unit.change)
        return Path(change) / "tasks.md"

    def _fail(self, unit: Unit, detail: str) -> RunOutcome:
        # Recorded rather than left at "planned": the next round would
        # otherwise pick it up and repeat the same failing work.
        self.log(f"failed: {detail}")
        self.store.set_state(unit.id, "failed")
        mark_groups(self._tasks(unit), unit.groups, done=False)
        return RunOutcome(status="failed", detail=detail)
