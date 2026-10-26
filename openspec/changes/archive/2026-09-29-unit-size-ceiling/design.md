# Design

## Two halves that must agree

Unit size is decided in two places and they have to say the same thing. The
planner is an <redacted> told to group task groups "until the estimate reaches about
{min_lines}"; `units.py` then packs deterministically, appending groups and
flushing when the accumulated estimate crosses that floor. The floor is passed to
both, so they agree today. The ceiling goes to both for the same reason: a
ceiling only the prompt knows about is a suggestion, and a ceiling only the
packer knows about produces plans the planner did not intend.

The packer is the half that makes it true. An <redacted> told a limit will usually
respect it; a `while` loop that flushes at the ceiling always will. Rejecting a
plan that exceeds it is the backstop for the case the packer cannot fix — a
single group too large on its own.

## A group that cannot be planned under the ceiling

The planner can only group what the change's tasks give it. When one task group's
own estimate exceeds the ceiling, no grouping helps: the change was authored too
coarsely, and the fix is in its `tasks.md`, not in the plan. Rejecting the plan
and re-asking would spend attempts on something the planner cannot solve, so that
case is reported as what it is — the change needs its tasks split — and the
change is left unplanned rather than planned badly.

## Why this stops at planning

An estimate is a guess made before the code exists. It is the right input for
grouping, because nothing better is available when the plan is made, and it is
not evidence about what a branch will contain.

The tempting next step is to measure the branch and stop a unit that came in
over the ceiling. This change deliberately does not, for one reason worth
recording: a ceiling that shapes plans is advice to the planner, while a ceiling
that blocks a push is a verdict on finished work, and those need separate
decisions. What should happen to a 1400-line branch whose spec said 600 — hold it,
label it, split it, merge it anyway — is a question about review workflow, not
about planning, and answering it here would smuggle a policy in behind a
configuration default.

**What that leaves uncaught, plainly.** A unit estimated at 520 lines landed 5032
across 54 files in this workspace. A planning cap would not have stopped it: the
estimate was under the ceiling and nothing checks afterwards. The value here is
narrower — plans stop combining groups into oversized units, and changes whose
groups are too coarse to build one at a time are named as such at plan time
instead of discovered at review time.

## What counts as a changed line

The same definition the planner's prompt already uses: additions plus deletions,
excluding generated files such as lockfiles. Since nothing is measured, this
stays a matter of instruction to the planner rather than a computation, and no
component needs to learn which files are generated.

## Why not bound the review surface instead

A ceiling on lines is crude: a 1200-line change that is one mechanical
substitution is easier to review than 300 lines of concurrency. A better measure
would weigh what the diff touches.

Crude is acceptable because the number only shapes how groups are combined. It is
not a gate, nothing fails because of it, and a better heuristic can replace it
without changing anything else.
