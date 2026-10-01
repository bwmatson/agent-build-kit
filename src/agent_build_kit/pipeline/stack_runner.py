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
from collections.abc import Callable, Collection, Sequence
from functools import partial
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

from agent_build_kit.config import active, models
from agent_build_kit.forges.base import BaseMissing
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.pr_body import build_pr_body, satisfied_reason
from agent_build_kit.pipeline.pr_replies import last_json
from agent_build_kit.pipeline.restack import HostMoved
from agent_build_kit.pipeline.task_progress import mark_groups
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import (
    HELD,
    IN_REVIEW,
    PLANNED,
    SATISFIED,
    Unit,
    branch_name,
    later_groups_by_change,
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
# A unit whose base moved before its push, or was gone when its pull request was
# opened: its next run moves the branch onto the base as it now is.
RESTACK = "restack"


def starting_step(unit: StoredUnit) -> tuple[str, str]:
    """The step a run of this stored unit starts at, and the model it names.

    Mirrors the branch order in `StackRunner.run`: a recorded review or verify
    resume first, then waiting feedback (a rework), else the build. Verify
    calls no model, and says so. A fresh build is named `implement`, the step
    that opens `StackRunner.run`'s build (its tests come first within it); a
    resume recorded at `tests` keeps that name, as it is where the run picks up.
    """
    resume = unit.resume_from
    if resume in (REVIEW, REWORK_REVIEW, VERIFY):
        step = resume
    elif unit.feedback:
        step = REWORK
    elif resume == TESTS:
        step = TESTS
    else:
        step = IMPLEMENT
    role = models()
    named = {
        REVIEW: role.review,
        REWORK_REVIEW: role.rework_review,
        REWORK: role.rework,
        TESTS: role.implement,
        IMPLEMENT: role.implement,
        VERIFY: "none",
    }
    return step, named[step]


# The change lives in the planning repo, which the run can read because
# `build_run_claude` passes `--add-dir`. Named by path rather than driven by
# `/opsx:apply`: that command exists only where OpenSpec is installed, which
# is the planning repo, while the unit is built in the target repo's worktree.
CHANGE_DIR = "{planning_repo}/openspec/changes/{change}"

# Where a change's deferred follow-ups accumulate: approved alongside, not
# worth a round, recorded here for the change's next unit and this PR's
# reviewer to see (design.md, "Deferral").
FOLLOW_UPS_FILE = "follow-ups.md"

FOLLOW_UPS_NOTE = """\
**Left by an earlier unit of this change, approved but not required of it:**

{items}
"""


def _follow_ups_marker(unit_id: str) -> str:
    return f"## From `{unit_id}`\n\n"


def _follow_ups_block_end(content: str, start: int, marker: str) -> int:
    """Where this unit's block ends in `content`: the next unit's marker, or the end."""
    # Line-anchored: a marker inside a point's text is not a block boundary.
    next_marker = content.find("\n## From `", start + len(marker) - 1)
    return next_marker + 1 if next_marker != -1 else len(content)


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
{boundary}
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

# What tier 1's output is saved under, whichever step it stopped: it is how
# every later step tells a failed check from a reviewer's comment.
TIER1_FAILED = "tier 1 failed:"

CHECKS_PROMPT = """\
The pipeline's checks (lint, formatting, types and the tests) failed on this
branch, for change {change_dir}, task group(s) {groups}. Nothing has been
reviewed yet: a reviewer is only asked once these pass.

---
{feedback}
---
{boundary}
Fix every failure above, and look for others of the same kind, so the next run
of the checks does not find them. The output may be cut short; run the checks
yourself to see all of it. Fix the cause, not the report: do not suppress a
rule, loosen a type to `Any`, or skip a test to make a check pass unless the
rule itself is wrong for this code, and then say so.

Run linting, formatting, types and the tests before you finish, and finish only
when all of them pass. Beyond fixing the checks, keep the change to what the
task groups ask for.
The change's files are read-only for you: do not tick boxes in its tasks.md
or edit anything under {change_dir}. The pipeline records a task as done once
the unit has passed review, tier 1 and been pushed.
"""


# The only follow-up kind that does not block approval. Anything else — a
# correctness problem, a test that would pass regardless, a missing test the
# task asked for, or something the command policy forbids — is inconvenient,
# not deferrable, and comes back to the builder whatever `approved` says.
DEFERRABLE_KIND = "optional"

# The two things a round can escalate instead of spending another one on:
# a class of problem no list can finish, or a disagreement already raised
# once. See design.md.
ESCALATIONS = ("class", "disagreement")


class FollowUp(Frozen):
    kind: str
    point: str


class Finding(Frozen):
    id: str = ""
    file: str
    line: int | None = None
    summary: str
    consequence: str = ""
    done: str = ""
    required: bool = False


class EarlierAnswer(Frozen):
    id: str
    status: str  # "fixed" | "open" | "declined"


# Optional findings past this many are left out of the feedback: a long tail of
# asides buries the required ones and buys a round of polish.
MAX_OPTIONAL = 5

NO_CONSEQUENCE = "(no consequence stated)"


def _where(finding: Finding) -> str:
    return f"{finding.file}:{finding.line}" if finding.line is not None else finding.file


def _render_one(finding: Finding, status: str = "") -> str:
    where = _where(finding)
    tag = f"[{finding.id}] " if finding.id else ""
    suffix = f" (reported {status})" if status else ""
    lines = [f"- {tag}{where}{suffix} — {finding.summary}"]
    consequence = finding.consequence or (NO_CONSEQUENCE if finding.required else "")
    if consequence:
        lines.append(f"  Consequence: {consequence}")
    if finding.done:
        lines.append(f"  Done when: {finding.done}")
    return "\n".join(lines)


def render_findings(findings: Sequence[Finding]) -> str:
    """The builder's feedback text for a findings list: required first."""
    sections = []
    for heading, required in (("Required", True), ("Optional", False)):
        items = [_render_one(f) for f in findings if f.required is required]
        if items:
            sections.append(f"{heading}:\n" + "\n".join(items))
    return "\n\n".join(sections)


def cap_optional(findings: Sequence[Finding]) -> tuple[list[Finding], int]:
    """The findings to show, and how many optional ones were left out.

    Required findings are never cut.
    """
    kept, cut, optional = [], 0, 0
    for finding in findings:
        if not finding.required:
            optional += 1
            if optional > MAX_OPTIONAL:
                cut += 1
                continue
        kept.append(finding)
    return kept, cut


class Verdict(Frozen):
    """A reviewer's reply, fully parsed.

    `parse_verdict` never raises: a reviewer that stops answering properly
    must not become invisible by being read as one that approved.
    """

    approved: bool = False
    feedback: str = ""
    needs_human: bool = False
    follow_ups: tuple[FollowUp, ...] = ()
    escalate: str = ""  # "" | "class" | "disagreement"
    reasoning: str = ""
    findings: tuple[Finding, ...] = ()
    # None when the reply has no `earlier` key. That answers nothing by id, so
    # it reads as `()`: an earlier required finding not already recorded fixed
    # or declined stays open. Earlier rounds with no ids (the prose shape) have
    # nothing to answer, so a prose-shaped reply still approves over them.
    earlier: tuple[EarlierAnswer, ...] | None = None

    @property
    def blocking(self) -> tuple[FollowUp, ...]:
        return tuple(f for f in self.follow_ups if f.kind != DEFERRABLE_KIND)

    @property
    def deferrable(self) -> tuple[FollowUp, ...]:
        return tuple(f for f in self.follow_ups if f.kind == DEFERRABLE_KIND)


def _readable_finding(item: object) -> object:
    """A finding's own fields only, with a line that is not a number left unset.

    An extra key or a range like "12-15" must not turn an otherwise readable
    finding into an unreadable, blocking one.
    """
    if not isinstance(item, dict):
        return item
    fields = {k: v for k, v in item.items() if k in Finding.model_fields and k != "id"}
    line = fields.get("line")
    if line is not None and (isinstance(line, bool) or not isinstance(line, int)):
        fields["line"] = None
    return fields


def _parse_findings(raw: object) -> tuple[Finding, ...]:
    if not raw:
        return ()
    items = raw if isinstance(raw, list) else [raw]
    out = []
    for item in items:
        try:
            out.append(Finding.model_validate(_readable_finding(item)))
        except ValueError:
            # As with an unreadable follow-up: one the pipeline cannot read
            # cannot be trusted to be optional, so it blocks.
            out.append(Finding(file="(unreadable)", summary=json.dumps(item), required=True))
    return tuple(out)


def _parse_answers(raw: object) -> tuple[EarlierAnswer, ...] | None:
    if raw is None:
        return None
    items = raw if isinstance(raw, list) else [raw]
    out = []
    for item in items:
        # Only `id` and `status` are read, leniently: an extra key, a numeric id
        # or a capitalised status is still the answer the reviewer meant.
        if isinstance(item, dict) and item.get("id") is not None and item.get("status"):
            out.append(
                EarlierAnswer(
                    id=str(item["id"]).strip(), status=str(item["status"]).strip().lower()
                )
            )
    return tuple(out)


def parse_verdict(output: str) -> Verdict:
    """A reviewer's reply, read as a verdict.

    An unreadable reply is not an approval. Reading it as one would make a
    reviewer that had stopped answering properly invisible — the branch would
    sail through on a parse failure, which is the one outcome worse than a
    reviewer that rejects everything.
    """
    match = re.search(r"\{.*\}", output, re.DOTALL)
    if not match:
        return Verdict(feedback="the reviewer's reply was not readable as a verdict")
    try:
        payload = json.loads(match.group(0))
    except ValueError:
        return Verdict(feedback="the reviewer's reply was not readable as a verdict")
    follow_ups = []
    raw = payload.get("follow_ups") or []
    if not isinstance(raw, list):
        raw = [raw]
    for item in raw:
        try:
            follow_ups.append(FollowUp.model_validate(item))
        except ValueError:
            # Not skipped: a follow-up the pipeline cannot read is not one it
            # can trust to be optional, so it blocks the approval same as a
            # correctness point would.
            point = item.get("point") if isinstance(item, dict) else item
            text = point if isinstance(point, str) and point else json.dumps(item)
            follow_ups.append(FollowUp(kind="unreadable", point=text))
    escalate = str(payload.get("escalate") or "").strip()
    return Verdict(
        findings=_parse_findings(payload.get("findings")),
        earlier=_parse_answers(payload.get("earlier")),
        approved=bool(payload.get("approved")),
        feedback=str(payload.get("feedback") or "").strip(),
        needs_human=bool(payload.get("needs_human")),
        follow_ups=tuple(follow_ups),
        escalate=escalate if escalate in ESCALATIONS else "",
        reasoning=str(payload.get("reasoning") or "").strip(),
    )


REWORK_PROMPT = """\
Review asked for a change to the work already on this branch, specified at
{change_dir}, task group(s) {groups}. This is PR #{pr}.

---
{feedback}
---
{boundary}
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

# Given to every build-side prompt above, only when this change has units
# after this one: naming what belongs to them is what stops a capable agent
# finishing that work too, once it notices the next group is one edit away —
# or a review comment names it, which is just as much an invitation.
BUILD_BOUNDARY_NOTE = """
Task group(s) {later} belong to later units of this change, each its own pull request.
Leave them alone even where their code looks one edit away, or where review
feedback names one of them: pulling that work forward makes this pull request
bigger than the plan intended, and leaves the change's record of what is done
crediting the wrong unit. Where feedback names something that belongs to a
later group, answer that in your account instead of implementing it — the
unit that owns the group is where it gets addressed.
"""

# Given to the reviewer alongside the build boundary above: the same groups,
# so a finding whose fix belongs there is reported rather than required.
REVIEW_BOUNDARY_NOTE = """**Task group(s) {later} belong to later units of this change.** A finding
whose fix is only there does not block this review — report it as belonging
to a later unit, not required of this one.
"""


def _later_text(unit: Unit, later: dict[str, tuple[int, ...]]) -> str:
    """The later groups as the boundary notes name them; a joined unit names each change."""
    if not unit.joined:
        return ", ".join(str(group) for group in later.get(unit.change, ()))
    return "; ".join(
        f"{', '.join(str(group) for group in groups)} of {change}"
        for change, groups in later.items()
    )


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

    @field_validator("reason", mode="before")
    @classmethod
    def _null_reason_is_empty(cls, value: object) -> object:
        """A null is what a model writes for "nothing to say"."""
        return "" if value is None else value


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

Decide each one as you port it:

- **keep** — still meaningful against the new base; carried over unchanged.
- **adapt** — still meaningful, but changed to fit the predecessor's new shape.
  Say what changed.
- **retire** — no longer meaningful, because of a specific change in the
  predecessor. Name the change. "It fails" or "it was hard to port" is not a
  reason: a test that still describes behaviour this unit's tasks require is
  kept or adapted, whatever it takes.

Only a test you do not carry over unchanged needs an entry in the JSON below —
one carried over unchanged is counted as kept automatically.

Write any test the tasks require that the previous work did not have. Run
linting, formatting, types and the tests before you finish.

The change's files are read-only for you: do not tick boxes in its tasks.md
or edit anything under {change_dir}.

Finish with JSON and nothing after it:

{{"tests": [{{"name": "<test name>", "decision": "keep|adapt|retire",
             "reason": "..."}}],
 "summary": "what changed in porting, for the reviewer"}}
"""

# Given when the adapt step's accounting is incomplete: the checker's own
# problems, and nothing else, so the agent finishes what it was one line from
# rather than redoing the port.
ADAPT_FOLLOWUP_PROMPT = """Your accounting of this unit's tests is not complete:

{problems}

Decide each one — keep, adapt or retire, with a reason naming what in the
predecessor made a retirement necessary. The code is already ported; only the
accounting is outstanding. Do not change any files.

Finish with JSON and nothing after it, covering every decision made so far,
not only what was missing:

{{"tests": [{{"name": "<test name>", "decision": "keep|adapt|retire",
             "reason": "..."}}]}}
"""

# Given to a review that follows a rework in the same loop.
EARLIER_ROUNDS_NOTE = """\
**Earlier rounds of this review.** This is round {round} of the loop. What the
earlier rounds asked for, and what the builder said it did about each:

{rounds}

Check first that each point was done, or that the builder's reason for not
doing it holds. Answer every earlier required finding by id in `earlier`, as
`fixed`, `open`, or `declined` when the builder's reason holds; you cannot
approve while one is open or left unanswered.

Do not re-open points that are settled. Raise new problems only in what the
reworks changed, or ones genuinely missed before — and for those, say why they
were not visible earlier.
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


# Given before every round, first included, so the reviewer can weigh a
# residual observation against losing correct work rather than judging in a
# vacuum. See design.md, "Telling the reviewer what it is spending".
ROUND_BUDGET_NOTE = """\
**Round budget.** This is round {round} of {total}, with {remaining} remaining \
after this one. {stake} Weigh a residual observation against losing correct \
work — hold this to the bar you would approve, not to perfection.
"""

_SPENT_MORE = (
    "If the budget runs out without an approval, the work is not merged and "
    "nothing is approved: the branch is pushed and held for a person, with "
    "the open points on its PR."
)
_SPENT_LAST = (
    "This is the final round: if it does not end in approval, the work is not "
    "merged and nothing is approved — the branch is pushed and held for a "
    "person, with the open points on its PR."
)


def _round_budget_note(round_number: int, total: int) -> str:
    remaining = total - round_number
    return ROUND_BUDGET_NOTE.format(
        round=round_number,
        total=total,
        remaining=remaining,
        stake=_SPENT_LAST if remaining == 0 else _SPENT_MORE,
    )


# Enough of each round for the reviewer to check it against, without one long
# round crowding out the rest of the prompt.
ROUND_CHARS = 4000


RESOLVED = ("fixed", "declined")


def _recorded(entry: dict) -> Finding:
    return Finding.model_validate({k: v for k, v in entry.items() if k in Finding.model_fields})


def _open_entries(
    rounds: Sequence[dict], earlier: Sequence[EarlierAnswer] | None
) -> list[tuple[dict, str]]:
    """Earlier required findings this verdict leaves open or unanswered, with
    the status the reviewer gave each ("" when it did not answer)."""
    answers = {a.id: a.status for a in earlier or ()}
    return [
        (f, answers.get(str(f["id"]), ""))
        for entry in rounds
        for f in entry.get("findings") or []
        if f.get("required") and answers.get(str(f["id"]), f.get("status")) not in RESOLVED
    ]


def _unresolved(rounds: Sequence[dict], earlier: Sequence[EarlierAnswer] | None) -> list[str]:
    """Ids of earlier required findings this verdict leaves open or unanswered."""
    return [str(f["id"]) for f, _ in _open_entries(rounds, earlier)]


def _render_open(rounds: Sequence[dict], earlier: Sequence[EarlierAnswer] | None) -> str:
    """The earlier findings still open, each whole: the builder reads this text
    and never the stored rounds, so an id alone would give it nothing to act on."""
    items = [_render_one(_recorded(f), status) for f, status in _open_entries(rounds, earlier)]
    return "Still open from earlier rounds:\n" + "\n".join(items) if items else ""


def _apply_answers(rounds: Sequence[dict], earlier: Sequence[EarlierAnswer] | None) -> list[dict]:
    answers = {a.id: a.status for a in earlier or ()}
    return [
        {
            **entry,
            "findings": [
                {**f, "status": answers.get(str(f.get("id")), f.get("status", ""))}
                for f in entry.get("findings") or []
            ],
        }
        if entry.get("findings")
        else entry
        for entry in rounds
    ]


def _fit(carried: list[tuple[str, str]]) -> set[int]:
    """Which of the (status, rendered) findings to leave out to fit ROUND_CHARS.

    Whole findings only, reported-fixed first, then declined, each oldest
    first; a finding is never truncated. One not yet fixed or declined is never
    left out, even over the limit: the reviewer must answer it.
    """
    order = {"fixed": 0, "declined": 1}
    dropped: set[int] = set()
    total = sum(len(text) for _, text in carried)
    for index, (_, text) in sorted(
        ((i, c) for i, c in enumerate(carried) if c[0] in order),
        key=lambda item: (order[item[1][0]], item[0]),
    ):
        if total <= ROUND_CHARS:
            break
        dropped.add(index)
        total -= len(text)
    return dropped


def _earlier_rounds(rounds: Sequence[dict]) -> str:
    if not rounds:
        return ""
    carried = [
        (str(f.get("status") or ""), _render_one(_recorded(f), str(f.get("status") or "")))
        for entry in rounds
        for f in entry.get("findings") or []
        if f.get("required")
    ]
    dropped = _fit(carried)
    parts = []
    index = 0
    for number, entry in enumerate(rounds, start=1):
        response = str(entry.get("response", "")).strip()[:ROUND_CHARS] or "(no account given)"
        if not (entry.get("findings") or entry.get("judged")):
            asked = str(entry.get("asked", "")).strip()[:ROUND_CHARS]
            parts.append(f"Round {number} asked:\n{asked}\n\nThe builder's response:\n{response}")
            continue
        judged = str(entry.get("judged") or "")
        lines = [f"Round {number} judged commit {judged}." if judged else f"Round {number}."]
        prose = str(entry.get("prose", "")).strip()[:ROUND_CHARS]
        if prose:
            lines.append(prose)
        for f in entry.get("findings") or []:
            if f.get("required"):
                if index not in dropped:
                    lines.append(carried[index][1])
                index += 1
        lines.append(f"The builder's response:\n{response}")
        parts.append("\n".join(lines))
    body = "\n\n---\n\n".join(parts)
    last = next((str(e["judged"]) for e in reversed(rounds) if e.get("judged")), "")
    if last:
        body += f"\n\nWhat changed since the last judged commit is `git diff {last}..HEAD`."
    if dropped:
        body += (
            f"\n\n{len(dropped)} earlier required finding(s) left out to keep this "
            "short, those reported fixed first."
        )
    return EARLIER_ROUNDS_NOTE.format(round=len(rounds) + 1, rounds=body)


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


def tests_needing_decision(
    old_tests: Sequence[str], present: set[str], changed: set[str]
) -> list[str]:
    """Which of the unit's previous tests the adapt step must account for.

    A test present and not in `changed` survived the replay untouched, so it
    counts as kept without being asked about. Missing from `present`, or
    present but in `changed`, is exactly where a silent drop could hide.
    """
    return [name for name in old_tests if name not in present or name in changed]


def check_test_decisions(
    old_tests: Sequence[str],
    decisions: Sequence[PortedTest],
    present: set[str],
    changed: Collection[str] = frozenset(),
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
            if name not in present:
                problems.append(
                    f"no decision for `{name}`, which is no longer in the tree — retire it "
                    "with a reason naming what in the predecessor made it invalid, or mark it "
                    "adapt and name the test that replaced it"
                )
            elif name in changed:
                problems.append(
                    f"no decision for `{name}`, which differs from the previous work — mark it "
                    "adapt and say what changed, or retire it with a reason"
                )
            else:
                problems.append(f"no decision for `{name}`")
        elif decision.decision not in ("keep", "adapt", "retire"):
            problems.append(f"`{name}`: unknown decision {decision.decision!r}")
        elif decision.decision == "retire" and len(decision.reason.strip()) < 20:
            problems.append(f"`{name}` retired without a reason naming the predecessor's change")
        elif decision.decision == "keep" and name not in present:
            problems.append(f"`{name}` is marked keep but is not in the tree")
        elif decision.decision == "keep" and name in changed:
            problems.append(
                f"`{name}` is marked keep but differs from the previous work — mark it "
                "adapt and say what changed"
            )
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
    # Called with `resolve=False` before a push: then a conflict is reported as
    # `Restacked.conflict` with the branch left where it was, and no agent runs.
    restack_onto: Callable[..., Restacked | None]
    run_tier1: Callable[..., tuple[bool, str]]
    run_tier2: Callable[..., tuple[bool, str]]
    push: Callable[..., str]
    open_pr: Callable[..., int]
    post_status: Callable[[str, bool], None]
    # Posts the reason on a satisfied unit's already-open pull request, then
    # closes it. A no-op default: most units never reach `satisfied` holding
    # one. See `wiring.build_close_pr`.
    close_pr: Callable[[Unit, int, str], None] = lambda unit, pr, reason: None
    # Whether the branch in the tree still sits on its base ref, which the PR
    # body reports whichever host renders the stack. See `pr_body`.
    linear: Callable[[Path, str], bool] = lambda tree, base: True
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
    # Tests whose content differs between the given ref — the adapt step's
    # old-work ref — and the tree, including one gone from a file it was in,
    # so a test that survived the replay by name only is not mistaken for one
    # the replay left alone.
    tests_changed: Callable[[Path, str], set[str]] = lambda tree, ref: set()
    # Brings the repo's remote refs up to date, in the repo's turn. Raises when
    # the remote cannot be reached; the runner logs that and carries on.
    fetch: Callable[[Unit], None] = lambda unit: None
    # The unit's base as it is now: the parent's pull request asked of the
    # forge, a merge the store has not heard of recorded, the branch to build
    # on named. Given the base the run started on.
    fresh_base: Callable[[Unit, str], str] = lambda unit, base: base
    # Each step as it starts and how it ended, so the tick log says where a
    # unit has got to rather than going quiet for the length of a build.
    log: Callable[[str], None] = lambda message: None

    def run(
        self, unit: Unit, *, base: str, graph: list[StoredUnit], rebased: bool = False
    ) -> RunOutcome:
        allowed, why = self.may_start()
        if not allowed:
            # Before anything else: pausing here costs nothing, while pausing
            # after the first run leaves a worktree and a half-built unit.
            return RunOutcome(status="paused", detail=why)

        branch = branch_name(unit)
        later = _later_text(unit, later_groups_by_change(unit, graph))
        build_boundary = BUILD_BOUNDARY_NOTE.format(later=later) if later else ""
        review_boundary = REVIEW_BOUNDARY_NOTE.format(later=later) if later else ""
        # From the store, not the passed-in unit: `run` takes a `Unit`, and
        # the store is what the poller wrote the review's words to.
        feedback = self.store.get(unit.id).feedback
        change_dir, groups = self._scope(unit)
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
            self._fetch(unit)
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
        # Whether this unit's own work is on the branch at all, judged once
        # below after whichever path ran — a fresh build, a rework, or a
        # resume — rather than from what that path reports about itself. A
        # run can finish cleanly having written nothing, and a restack can
        # drop a rework's only commit when the predecessor already carries
        # the same change. Either way there is nothing here to review or
        # push, only tier 1 to judge it by.
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
            failed_check = feedback.startswith(TIER1_FAILED)
            self.log(
                f"step: {'fix the failing checks' if failed_check else 'address the review'} "
                f"it stopped before ({models().rework})"
            )
            response = self.run_rework(
                (CHECKS_PROMPT if failed_check else REVIEW_FEEDBACK_PROMPT).format(
                    change_dir=change_dir, groups=groups, feedback=feedback, boundary=build_boundary
                ),
                cwd=tree,
            )
            if not failed_check:
                # A failed check has no reviewer to answer; recording this
                # would overwrite the last review round's answer.
                self._record_response(unit, response)
            self.commit(
                f"fix: {unit.title} ({'checks' if failed_check else 'review'}, resumed)",
                cwd=tree,
            )
            needs_review = True
        elif feedback:
            # One run, not the usual pair. The tests and implementation are
            # already on the branch and were green when it was pushed, so
            # re-running the tests step would write tests that exist and the
            # implementation prompt knows nothing of what was objected to.
            # Its own call, on the review model: deciding what a reviewer
            # meant is judgement work, and it only ran on the implementation
            # model because it shared `run_claude`'s plumbing.
            failed_check = feedback.startswith(TIER1_FAILED)
            self.log(f"step: rework from feedback ({models().rework})")
            answer = self.run_rework(
                CHECKS_PROMPT.format(
                    groups=groups,
                    change_dir=change_dir,
                    feedback=feedback,
                    boundary=build_boundary,
                )
                if failed_check
                else REWORK_PROMPT.format(
                    groups=groups,
                    change_dir=change_dir,
                    feedback=feedback,
                    pr=self.store.get(unit.id).pr or "(not yet opened)",
                    boundary=build_boundary,
                ),
                cwd=tree,
            )
            self.commit(f"fix: {unit.title}", cwd=tree)
            if answer and self.store.get(unit.id).pr and not failed_check:
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
            # Given to both build prompts: a unit resumed at IMPLEMENT skips
            # the tests prompt entirely, and would otherwise never see what an
            # earlier unit left for this one to act on.
            follow_ups_note = self._follow_ups_note(unit)
            if resume != IMPLEMENT:
                self.store.record_step(unit.id, TESTS)
                self.log(f"step: write the tests ({models().implement})")
                tests_prompt = TESTS_PROMPT.format(
                    groups=groups, change_dir=change_dir, boundary=build_boundary
                )
                if follow_ups_note:
                    tests_prompt = f"{follow_ups_note}\n\n{tests_prompt}"
                self.run_claude(tests_prompt, cwd=tree)
                self.commit(f"test: {unit.title}", cwd=tree)
                if outcome := checkpoint(IMPLEMENT):
                    return outcome

            self.log(f"step: implement ({models().implement})")
            before = self.branch_commits(tree, ref)
            implementation_prompt = IMPLEMENTATION_PROMPT.format(
                groups=groups, change_dir=change_dir, boundary=build_boundary
            )
            if follow_ups_note:
                implementation_prompt = f"{follow_ups_note}\n\n{implementation_prompt}"
            self.run_claude(implementation_prompt, cwd=tree)
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
                # Empty for any other reason is not judged here: the unified
                # check below judges the branch itself, and tier 1 after it
                # judges a branch with nothing on it at all.
            needs_review = True

        # Judged once, on the branch itself, after whichever path above ran:
        # a restack can drop a rework's only commit when the predecessor now
        # carries the same change, and a fresh run can finish cleanly having
        # written nothing — neither is visible from what that path reports
        # about itself.
        if self.branch_commits(tree, ref) == 0:
            produced_nothing = True
            needs_review = False

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
                ref,
                build_boundary,
                review_boundary,
            )
            if isinstance(approved, RunOutcome):
                return approved
            if not approved:
                # The budget ran out with blocking work still outstanding —
                # not a bad run, so not a discard. `why` already carries every
                # outstanding point. Set before the checkpoint, so the points
                # survive the hold even if the checkpoint stops the push.
                self.store.set_feedback(unit.id, why)
                # The same gate the normal path clears before pushing: a base
                # that moved while the rounds ran would otherwise put the
                # parent's old commits in this unit's diff.
                if outcome := checkpoint(VERIFY, usage=False):
                    return outcome
                return self._spend_rounds(unit, tree, branch, graph, base, why)

        # Past this point nothing is a Claude run, so only upstream can stop it.
        if outcome := checkpoint(VERIFY, usage=False):
            return outcome

        # Tier 1 does not run again after a review. A reviewer reports and the
        # builder fixes, so approval leaves the branch as the checks before it
        # judged it; a second run would prove nothing new. The branch is
        # checked again only when it changes: a clean move onto a new base below,
        # and a conflicted one is resolved by the adapt step, which accounts for
        # its own tests. A unit that produced nothing has no review and no
        # earlier check, so tier 1 is the whole judgement of it.
        if produced_nothing:
            # Whole-repo: a diff-scoped tier 1 would lint an empty range and
            # test nothing, which is not proof that anything actually passes.
            # See `wiring.build_tier1`.
            self.log("step: tier 1")
            tier1_ok, tier1_output = self.run_tier1(cwd=tree, base=ref, whole_repo=True)
            self.log(f"tier 1 {'passed' if tier1_ok else 'failed'}")
            if not tier1_ok:
                # Kept, not thrown away. Both pilot units failed here and a
                # retry knew nothing about why, so it re-ran both expensive
                # prompts and rebuilt the same branch. Recorded as feedback, a
                # retry is one scoped run against the actual failure.
                self.store.set_feedback(unit.id, f"{TIER1_FAILED}\n{tier1_output}".strip())
                return self._fail(unit, "tier 1 failed")

            # Nothing of this unit's own on the branch, and what is already at
            # the tip passes — the work its groups called for arrived another
            # way. Judged here, on the branch and the checks, never on the
            # build step's own report: that is the same sentence a run that
            # wrote nothing and should have failed would also produce.
            self.log("nothing to add and tier 1 passes — satisfied")
            self.store.set_state(
                unit.id, SATISFIED, note="already implemented; tier 1 passed", resume_from=""
            )
            # Cleared the same as the in_review path below clears them: a
            # satisfied unit is done, and nothing here should look like a
            # build still in progress if it is ever inspected or resumed.
            if self.store.get(unit.id).predecessor_note:
                self.store.set_predecessor_note(unit.id, "")
            if self.store.get(unit.id).review_rounds:
                self.store.set_review_rounds(unit.id, ())
            # The review feedback and its replies belong to a build this unit
            # is no longer doing; the PR is closed below with the reason.
            if self.store.get(unit.id).feedback:
                self.store.set_feedback(unit.id, "")
            if self.store.get(unit.id).pending_replies:
                self.store.set_pending_replies(unit.id, ())
            stored = self.store.get(unit.id)
            if stored.pr:
                # A rework that finds the work has landed elsewhere in the
                # meantime leaves an open pull request with no diff and no
                # future. Posting and closing are one call, so the reason is
                # never missing before the close. Neither this text nor the
                # decision to close asks a model anything: both are mechanical,
                # the same as everything else on this path.
                try:
                    self.close_pr(
                        unit, stored.pr, satisfied_reason(stored, graph=graph or [stored])
                    )
                except Exception as error:  # noqa: BLE001
                    # The unit stays satisfied regardless: a stale pull
                    # request is a nuisance, not a reason to revisit a
                    # judgement the branch and the checks already settled.
                    # But the failure is recorded on the unit itself, not only
                    # in a tick log someone would have to find — otherwise it
                    # looks identical to a unit whose close worked, and the PR
                    # sits open with no one told.
                    self.log(f"{unit.id}: pull request #{stored.pr} not closed — {error}")
                    self.store.set_state(
                        unit.id,
                        SATISFIED,
                        note=f"already implemented; tier 1 passed; PR #{stored.pr} not closed "
                        f"— {error}",
                    )
            self._mark(unit, done=True)
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

        # The base may have moved on the remote since this run began: a parent
        # merged, or the trunk advanced. Checked once, here, so what is pushed
        # sits on the base as it now is.
        self._fetch(unit)
        try:
            fresh = self.fresh_base(unit, base)
        except Exception as error:  # noqa: BLE001
            # Asking the forge is the network too: a unit that passed review
            # and tier 1 is not failed because the host did not answer.
            self.log(f"could not ask the forge for the base, going on with {base}: {error}")
            fresh = base
        if fresh != base:
            self.log(f"base is now {fresh}, not {base}")
            base, ref = fresh, local_ref(fresh)
        try:
            # Without the resolver: a resolution here would run outside the
            # usage gate and leave the branch rewritten with nothing telling
            # review it was. A conflict is aborted, and the resumed run's
            # restack resolves it the usual way.
            moved = self.restack_onto(tree=tree, branch=branch, base=ref, unit=unit, resolve=False)
        except (AgentRateLimited, AgentInterrupted):
            raise
        except Exception as error:  # noqa: BLE001
            return self._resume_for_base(
                unit, f"moving onto {base} needed resolution: {error}", base, graph, rebased
            )
        if moved is not None:
            if moved.conflict or moved.resolved:
                return self._resume_for_base(
                    unit, f"moving onto {base} needed resolution", base, graph, rebased
                )
            self.log(f"moved onto {base} cleanly before the push; tier 1 again")
            tier1_ok, tier1_output = self.run_tier1(cwd=tree, base=ref, whole_repo=False)
            if not tier1_ok:
                self.store.set_feedback(unit.id, f"{TIER1_FAILED}\n{tier1_output}".strip())
                return self._resume_for_base(unit, f"tier 1 failed on {base}", base, graph, rebased)
            if unit.tier == "tier2":
                # The moved commit is what gets pushed and what the status is
                # posted for, and it has not been through tier 2.
                self.log("tier 2 again on the moved commit")
                tier2_ok, snapshot = self.run_tier2(cwd=tree)
                if not tier2_ok:
                    self.store.set_feedback(unit.id, f"tier 2 failed:\n{snapshot}".strip())
                    return self._resume_for_base(
                        unit, f"tier 2 failed on {base}", base, graph, rebased
                    )

        # The rule, checked where it matters rather than inferred from the path
        # taken: the PR only ever receives the commit the review loop approved.
        head, approved_sha = self.head(tree), self.store.get(unit.id).approved
        if not approved_sha or head != approved_sha:
            return self._fail(
                unit,
                f"refusing to push {head[:9] or '?'}: review approved "
                f"{approved_sha[:9] or 'nothing'} on this branch",
            )
        try:
            sha = self.push(branch, cwd=tree)
        except HostMoved as moved:
            # Not pushed: the tree now holds the host's head, and review has
            # to pass it before anything goes to the PR.
            self.log(f"not pushed: {moved}")
            self.store.set_state(
                unit.id, PLANNED, note=f"not pushed: {moved}", resume_from=REWORK_REVIEW
            )
            return RunOutcome(status="held", detail=f"re-reviewing: {moved}")
        self.log(f"pushed {branch} at {sha[:9]}")

        # Only now, with the push confirmed: a follow-up recorded ahead of a
        # tier 1 or tier 2 failure would describe work that never left the
        # machine.
        # From the store, not this run: a unit resumed at VERIFY skips review.
        if self.store.get(unit.id).deferred:
            self._record_follow_ups(unit, self.store.get(unit.id).deferred)
            self.store.set_deferred(unit.id, ())

        stored = self.store.get(unit.id)
        # Both bodies: whether the host shows this PR in a stack is only known
        # once `open_pr` has asked it to, so that step picks.
        body = partial(
            build_pr_body,
            stored,
            graph=graph or [stored],
            base=base,
            tier2_snapshot=snapshot,
            # From the change's own record of this unit's follow-ups, not
            # this run's local `deferred`: a unit resumed at VERIFY skips
            # review and has none, a rework re-pushes without repeating
            # them, and a later approval must not lose an earlier one's.
            follow_ups=self._follow_ups_for(unit) or None,
            linear=self.linear(tree, ref),
        )
        try:
            pr = self.open_pr(
                unit,
                body=body(stacks=False),
                stacked_body=body(stacks=True),
                base=base,
                cwd=tree,
            )
        except BaseMissing as error:
            # The base was deleted between the check and the call, most often
            # by its merge: ask again, and go on from whatever it is now.
            try:
                base = self.fresh_base(unit, base)
            except Exception as asked:  # noqa: BLE001
                self.log(f"could not ask the forge for the base: {asked}")
            return self._resume_for_base(
                unit,
                str(error),
                base,
                graph,
                rebased,
                lead="base gone before its pull request",
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
        self._mark(unit, done=True)
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
        ref: str,
        build_boundary: str = "",
        review_boundary: str = "",
    ) -> tuple[bool | RunOutcome, str]:
        """Alternate review and rework until the reviewer approves, or give up.

        The first round reviews a freshly built branch; every round after
        reviews a rework, which is why the model differs between them.

        Returns what to fix (unused once approved or held). On approval the
        follow-ups the reviewer deferred rather than blocked on are recorded on
        the unit with the approval. A `False`
        with no `RunOutcome` means the round budget was spent with blocking
        work still outstanding — the one case `run` has to push and hold for
        rather than fail.
        """
        why = ""
        if not reworking:
            # A fresh build starts a fresh loop; a resumed or reworking one
            # carries the rounds it had.
            self.store.set_review_rounds(unit.id, ())
        total = active().limits.max_review_rounds
        for round_number in range(total):
            first = round_number == 0 and not reworking
            if outcome := checkpoint(REVIEW if first else REWORK_REVIEW):
                return outcome, why
            # Committed before the reviewer looks, so the verdict is on a commit
            # — the one recorded below, and the only one that may be pushed. It
            # used to be committed after approval, as "leftovers", which put an
            # unreviewed commit on top of the reviewed ones.
            self.commit(f"chore: {unit.title} (uncommitted work)", cwd=tree)
            # Before the reviewer is asked, not after it approves: a reviewer's
            # time goes on a branch that passes its checks. A failure goes
            # back to the builder, and only then is a review requested.
            stopped = self._fix_until_checks_pass(
                unit, tree, ref, change_dir, groups, checkpoint, build_boundary
            )
            if stopped is not None:
                return stopped, why
            judged = self.head(tree)
            model = models().review if first else models().rework_review
            self.log(f"step: review round {round_number + 1} ({model})")
            # A branch moved onto a changed predecessor tells its reviewer so,
            # with the instruction to check its tests still fit.
            stored = self.store.get(unit.id)
            notes = [
                f"This unit carries task group(s) {groups}, all of them its own work."
                if unit.joined
                else "",
                review_boundary,
                stored.predecessor_note,
                _round_budget_note(round_number + 1, total),
                _earlier_rounds(stored.review_rounds),
            ]
            text = "\n\n".join(n for n in notes if n)
            context = {"context": text} if text else {}
            raw = (self.run_review if first else self.run_rework_review)(cwd=tree, **context)
            verdict = parse_verdict(raw)

            # A blocking follow-up — correctness, a test that would pass
            # regardless, a missing test the task asked for, anything the
            # command policy forbids — overrides `approved`: deferral is for
            # work that can wait, not for work that is inconvenient.
            prose = verdict.feedback
            if verdict.blocking:
                points = "\n".join(f"- {f.point}" for f in verdict.blocking)
                prose = f"{prose}\n\n{points}".strip() if prose else points
            earlier_rounds = stored.review_rounds
            open_ids = _unresolved(earlier_rounds, verdict.earlier)
            still_open = _render_open(earlier_rounds, verdict.earlier)
            shown, cut = cap_optional(verdict.findings)
            if cut:
                self.log(f"{cut} optional finding(s) left out, over the {MAX_OPTIONAL} shown")
            bare = sum(1 for f in shown if f.required and not f.consequence)
            if bare:
                self.log(f"{bare} required finding(s) returned with no consequence stated")
            kept = [
                f.model_copy(update={"id": f"{len(earlier_rounds) + 1}.{n}"})
                for n, f in enumerate(shown, start=1)
            ]
            why = "\n\n".join(p for p in (prose, still_open, render_findings(kept)) if p)
            approved = (
                verdict.approved
                and not verdict.blocking
                and not open_ids
                and not any(f.required for f in verdict.findings)
            )

            if approved:
                sha = judged
                # One line each, so the change's file and the PR body read a
                # point back as the one item it was. Optional findings ride
                # with the deferred follow-ups rather than vanishing.
                points = tuple(
                    p
                    for p in (
                        *(" ".join(f.point.split()) for f in verdict.deferrable),
                        *(
                            " ".join(f"{_where(f)} — {f.summary}".split())
                            for f in shown
                            if not f.required
                        ),
                    )
                    if p
                )
                self.store.record_approval(unit.id, sha, points)
                self.log(f"review approved {sha[:9]}")
                if points:
                    self.log(f"deferred {len(points)} follow-up(s) to the change")
                return True, ""

            self.log(f"review asked for changes: {' '.join(why.split())[:300]}")
            rounds = tuple(_apply_answers(earlier_rounds, verdict.earlier))
            recorded = {
                "asked": why,
                "prose": prose,
                "response": "",
                "judged": judged,
                "findings": [{**f.model_dump(), "status": ""} for f in kept],
            }
            self.store.set_review_rounds(unit.id, (*rounds, recorded))
            if verdict.needs_human:
                # What is left is something the builder's environment refuses
                # (an edit to a file Claude Code protects). Asking again spends
                # rounds on a change it can never make, so stop and wait.
                self.store.set_feedback(unit.id, why)
                self.store.set_state(unit.id, HELD, note=f"needs a human: {why[:300]}")
                self.log(f"needs a human — held: {' '.join(why.split())[:300]}")
                return RunOutcome(status="held", detail=f"needs a human: {why[:200]}"), why
            # A class escalation needs an earlier round to be another instance
            # of; a disagreement needs the builder to have declined a point on
            # an earlier round, so both positions can go on the record. With
            # no earlier round — `rounds` here is what preceded this one —
            # neither holds, so an escalation on round one is an ordinary
            # rejection instead.
            declined = rounds and str(rounds[-1].get("response", "")).strip()
            escalate_now = bool(rounds) and (
                verdict.escalate == "class" or (verdict.escalate == "disagreement" and declined)
            )
            if escalate_now:
                # Another instance of a kind that cannot be enumerated, or a
                # point raised again after the builder already declined it: a
                # third exchange of prose is the least likely thing to settle
                # either, so this is a person's call, not another round.
                parts = [why]
                if verdict.escalate == "disagreement":
                    parts.append(str(rounds[-1].get("response", "")).strip())
                parts.append(verdict.reasoning)
                combined = "\n\n".join(p for p in parts if p).strip()
                self.store.set_feedback(unit.id, combined)
                label = (
                    "an open-ended class"
                    if verdict.escalate == "class"
                    else "a repeated disagreement"
                )
                reasoning_flat = " ".join(verdict.reasoning.split())[:280]
                self.store.set_state(
                    unit.id,
                    HELD,
                    note=f"escalated — {label} ({verdict.escalate}): {reasoning_flat}",
                )
                self.log(f"escalated ({verdict.escalate}) — held: {reasoning_flat}")
                return (
                    RunOutcome(
                        status="held",
                        detail=f"escalated ({verdict.escalate}): {reasoning_flat[:200]}",
                    ),
                    why,
                )
            if round_number == total - 1:
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
                REVIEW_FEEDBACK_PROMPT.format(
                    change_dir=change_dir, groups=groups, feedback=why, boundary=build_boundary
                ),
                cwd=tree,
            )
            self._record_response(unit, response)
            self.commit(f"fix: {unit.title} (review round {round_number + 1})", cwd=tree)
        return False, why

    def _fix_until_checks_pass(
        self,
        unit: Unit,
        tree: Path,
        ref: str,
        change_dir: str,
        groups: str,
        checkpoint: Callable[[str], RunOutcome | None],
        build_boundary: str,
    ) -> RunOutcome | None:
        """Run tier 1 before a review, and hand its failures back to the builder.

        Tier 1 used to run only after the reviewer approved, so a branch that
        did not lint or type-check was reviewed twice over: once to approve it,
        and again after the failure came back. The reviewer is also the more
        expensive model. Now the branch has to pass its own checks first, and a
        failure is a rework step on the saved output, up to
        `limits.max_check_rounds` of them, before it is failed.

        Returns None when the checks pass, else the outcome that ends the run:
        failed, or stopped by a pause. A budget of 0 is not "off": the branch is
        still checked, and a failure fails the unit with no fix attempt, since
        this is the only gate before a push.
        """
        budget = active().limits.max_check_rounds
        for attempt in range(budget + 1):
            self.log("step: checks before review")
            ok, output = self.run_tier1(cwd=tree, base=ref, whole_repo=False)
            self.log(f"checks {'passed' if ok else 'failed'}")
            if ok:
                if self.store.get(unit.id).feedback.startswith(TIER1_FAILED):
                    # Fixed. Left saved, a run stopped before its review would
                    # resume into the same fix and redo work already on the branch.
                    self.store.set_feedback(unit.id, "")
                return None
            # Kept before anything can stop the run, so the retry addresses
            # this output rather than running the checks to discover it.
            feedback = f"{TIER1_FAILED}\n{output}".strip()
            self.store.set_feedback(unit.id, feedback)
            if attempt == budget:
                return self._fail(
                    unit, f"checks still failing after {budget} fix round(s), before review"
                )
            if outcome := checkpoint(REWORK):
                return outcome
            self.log(f"step: fix the failing checks ({models().rework}), round {attempt + 1}")
            self.run_rework(
                CHECKS_PROMPT.format(
                    change_dir=change_dir, groups=groups, feedback=feedback, boundary=build_boundary
                ),
                cwd=tree,
            )
            self.commit(f"fix: {unit.title} (checks, round {attempt + 1})", cwd=tree)
        return None

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
        the rework model ports it — deciding, for each previous test the port did
        not carry over unchanged, whether it still belongs. Those decisions are
        checked here (each such test accounted for, every kept one present and
        unchanged, every retirement given a reason), then handed to the
        reviewer, who judges them.
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
                tests="\n".join(f"- `{name}`" for name in restacked.old_tests),
            ),
            cwd=tree,
        )
        self.commit(f"adapt: {unit.title} onto {restacked.onto_unit}", cwd=tree)

        # Only now, after the port, does the tree hold what the agent actually
        # carried over — reading it before the commit would see none of the
        # unit's own tests and narrow `required` to everything, every time.
        present = self.tests_in(tree)
        changed = self.tests_changed(tree, keep)
        required = tests_needing_decision(restacked.old_tests, present, changed)
        decisions = parse_test_decisions(answer)
        problems = check_test_decisions(required, decisions, present, changed)
        # A checker that is unhappy is put back to the agent, bounded: the
        # code already landed with the commit above, so a second miss costs
        # one short prompt rather than a re-port.
        for _ in range(active().limits.max_adapt_rounds - 1):
            if not problems:
                break
            answer = self.run_rework(
                ADAPT_FOLLOWUP_PROMPT.format(problems="\n".join(f"- {p}" for p in problems)),
                cwd=tree,
            )
            # Merged over the first answer's, not replacing it: an agent that
            # reads "decide each one" as only the ones just named would
            # otherwise drop decisions it already got right.
            by_name = {d.name: d for d in decisions}
            by_name.update({d.name: d for d in parse_test_decisions(answer)})
            decisions = list(by_name.values())
            problems = check_test_decisions(required, decisions, present, changed)
        if problems:
            why = "the adapt step did not account for its tests: " + "; ".join(problems)
            outstanding = [n for n in required if any(f"`{n}`" in p for p in problems)]
            if outstanding:
                why += "\n\noutstanding: " + ", ".join(f"`{n}`" for n in outstanding)
            waiting = self.store.get(unit.id).feedback
            self.store.set_feedback(unit.id, f"{waiting}\n\n{why}".strip())
            return self._fail(unit, why)

        rendered = "".join(
            f"\n- `{d.name}`: {d.decision}" + (f" — {d.reason}" if d.reason else "")
            for d in decisions
        )
        auto_kept = [name for name in restacked.old_tests if name not in required]
        kept_note = (
            "\n\nCarried over unchanged, so counted as kept without being asked about: "
            + ", ".join(f"`{name}`" for name in auto_kept)
            if auto_kept
            else ""
        )
        self.store.set_predecessor_note(
            unit.id,
            PREDECESSOR_NOTE.format(
                onto_unit=restacked.onto_unit,
                how="replaying this unit onto it conflicted, so its work was ported onto the "
                "new version by hand",
                decisions=(
                    f"The port decided, for its previous tests:{rendered}{kept_note}\n\nJudge "
                    "each decision, retirements especially. "
                )
                if decisions or auto_kept
                else "",
            ),
        )
        counts = {k: sum(d.decision == k for d in decisions) for k in ("keep", "adapt", "retire")}
        self.log(
            f"adapted: {counts['keep']} kept, {counts['adapt']} adapted, {counts['retire']} retired"
        )
        return None

    def _change_dir(self, change: str) -> str:
        return CHANGE_DIR.format(planning_repo=self.planning_repo, change=change)

    def _scope(self, unit: Unit) -> tuple[str, str]:
        """What a prompt names as the unit's change directory and task groups.

        A unit carrying nothing names its own, as it always has. One that
        carries groups of other changes names every change directory and each
        one's groups, all as this unit's own work.
        """
        members = unit.members()
        dirs = [self._change_dir(member.change) for member in members]
        numbers = [", ".join(str(group) for group in member.groups) for member in members]
        if len(members) == 1:
            return dirs[0], numbers[0]
        return (
            " and ".join(dirs),
            " and ".join(f"{n} of {d}" for n, d in zip(numbers, dirs, strict=True)),
        )

    def _mark(self, unit: Unit, *, done: bool) -> None:
        """Tick or untick each change's groups in that change's own tasks file."""
        for member in unit.members():
            tasks = Path(self._change_dir(member.change)) / "tasks.md"
            mark_groups(tasks, member.groups, done=done)

    def _follow_ups_path(self, unit: Unit) -> Path:
        return Path(self._change_dir(unit.change)) / FOLLOW_UPS_FILE

    def _follow_ups_note(self, unit: Unit) -> str:
        """What earlier units of this change deferred, for a fresh build to see.

        Read directly, like `tasks.md`: the planning repo is a real checkout
        the pipeline already reads and writes without an injected callable.
        """
        paths = [
            Path(self._change_dir(member.change)) / FOLLOW_UPS_FILE for member in unit.members()
        ]
        texts = [path.read_text().strip() for path in paths if path.exists()]
        content = "\n\n".join(text for text in texts if text)
        return FOLLOW_UPS_NOTE.format(items=content) if content else ""

    def _follow_ups_for(self, unit: Unit) -> list[str]:
        """This unit's own follow-ups, as last recorded — for its PR body.

        Read from the file rather than a run's local `deferred`: a unit
        resumed at VERIFY skips review and has none locally, a rework
        re-pushes without repeating them, and a later plain approval must not
        make an earlier one's follow-ups disappear from the PR.
        """
        path = self._follow_ups_path(unit)
        if not path.exists():
            return []
        content = path.read_text()
        marker = _follow_ups_marker(unit.id)
        start = content.find(marker)
        if start == -1:
            return []
        block = content[start + len(marker) : _follow_ups_block_end(content, start, marker)]
        return [line[2:].strip() for line in block.splitlines() if line.startswith("- ")]

    def _record_follow_ups(self, unit: Unit, items: Sequence[str]) -> None:
        if not items:
            return
        path = self._follow_ups_path(unit)
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(path.with_name(f"{path.name}.lock")):
            existing = path.read_text() if path.exists() else ""
            marker = _follow_ups_marker(unit.id)
            block = marker + "\n".join(f"- {i}" for i in items) + "\n\n"
            start = existing.find(marker)
            if start == -1:
                # First time this unit has deferred anything.
                path.write_text(existing + block)
                return
            # Replace its existing block in place rather than appending
            # another one: a retry, a PR-comment rework, or a restack
            # re-review must not leave a duplicate for the same unit.
            end = _follow_ups_block_end(existing, start, marker)
            path.write_text(existing[:start] + block + existing[end:])

    def _spend_rounds(
        self, unit: Unit, tree: Path, branch: str, graph: list[StoredUnit], base: str, why: str
    ) -> RunOutcome:
        """The round budget ran out with blocking work still outstanding.

        `held` is the honest state for work that exists and whose open points
        are written down (design.md, "The last round should not be a
        discard"): the branch is pushed and its PR carries the points, so a
        person inherits a branch and a list rather than an abandoned
        worktree. Nothing here is approved or merged — tier 1, tier 2 and the
        approved-commit push gate are all skipped, and no task is ticked.
        """
        try:
            sha = self.push(branch, cwd=tree)
        except HostMoved as moved:
            # Not a failure: the adoption replayed local commits onto the
            # host's head and recorded it, so the lease holds on a second push.
            # This path pushes unapproved work for a person by design.
            self.log(f"{moved} — pushing again")
            sha = self.push(branch, cwd=tree)
        self.log(f"pushed {branch} at {sha[:9]} — rounds spent, holding for a person")
        stored = self.store.get(unit.id)
        body = partial(
            build_pr_body,
            stored,
            graph=graph or [stored],
            base=base,
            open_points=why,
            follow_ups=self._follow_ups_for(unit) or None,
            linear=self.linear(tree, local_ref(base)),
        )
        pr = self.open_pr(
            unit, body=body(stacks=False), stacked_body=body(stacks=True), base=base, cwd=tree
        )
        self.store.set_state(
            unit.id,
            HELD,
            pr=pr,
            resume_from="",
            note=f"rounds spent with work outstanding: {' '.join(why.split())[:300]}",
        )
        self.log(f"held: rounds spent — #{pr}")
        return RunOutcome(status="held", detail=f"rounds spent, held as #{pr}")

    def _fetch(self, unit: Unit) -> None:
        """Bring the repo's remote refs up to date; a failure is logged, not fatal."""
        try:
            self.fetch(unit)
        except Exception as error:  # noqa: BLE001
            self.log(f"fetch failed, going on with the refs it has: {error}")

    def _resume_for_base(
        self,
        unit: Unit,
        why: str,
        base: str,
        graph: list[StoredUnit],
        rebased: bool,
        *,
        lead: str = "base moved before its push",
    ) -> RunOutcome:
        """Resume at the restack now, once, rather than queue.

        Usually nothing is pushed yet; when the pull request was refused for a
        missing base the branch is, and `lead` says so in the note. The resumed
        run resolves under the usage gate and tells review of it. A second hold
        in the same run is left planned for the next tick, so a base that keeps
        moving cannot loop.
        """
        note = f"{lead}: {why}"
        self.log(f"held: {note}")
        self.store.set_state(unit.id, PLANNED, note=note, resume_from=RESTACK)
        if rebased:
            return RunOutcome(status="held", detail=note)
        self.log(f"resuming at its restack on {base}")
        return self.run(unit, base=base, graph=graph, rebased=True)

    def _fail(self, unit: Unit, detail: str) -> RunOutcome:
        # Recorded rather than left at "planned": the next round would
        # otherwise pick it up and repeat the same failing work.
        self.log(f"failed: {detail}")
        self.store.set_state(unit.id, "failed")
        self._mark(unit, done=False)
        return RunOutcome(status="failed", detail=detail)
