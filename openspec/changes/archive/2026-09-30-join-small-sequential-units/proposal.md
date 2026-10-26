# Proposal

## Why

The planner already combines small consecutive task groups into one unit — but
only inside a change. Across changes it can only say "this depends on that".
So a run of small changes to the same module becomes a run of small pull
requests stacked one on another.

One afternoon's queue looked like this: five changes, each one unit, each
editing the same three modules, planned as a chain five deep — A, then B on A,
then C on B. None was large; three of them together were under the size
ceiling. The chain cost what chains cost:

- each one waited for the one before it to be reviewed and merged;
- each merge moved every branch above it, and two of those moves conflicted
  and needed an agent to resolve;
- five separate review loops read largely the same code;
- one failure at the head of the chain held the other four.

A person planning that work by hand would have put the related small pieces in
one pull request. That is what was done, by hand, twice that day — a new
requirement was added to an unstarted change's tasks instead of becoming a
change of its own.

The limit is in the model, not the planner's judgement: a unit belongs to
exactly one change.

## What Changes

- **A unit may carry task groups from more than one change.** It keeps one
  identity — its first change's name, branch and pull request — and records the
  groups it has taken from others. Building, reviewing, ticking tasks and
  archiving all follow each group back to its own change.
- **While planning a change, the planner looks for unstarted units to combine,**
  at the same time as it works out dependencies. Every unit that has not started
  is a candidate — the new change's and those already planned, whichever change
  they came from — so a new change may be joined onto an existing unit, and two
  existing units may be joined to each other. Two units are joined when all of
  these hold: same repo and tier; the two form a straight
  line (the later depends on the earlier, nothing else depends on the earlier,
  and the later waits on nothing else that is unfinished); the planner judges
  them related — they touch the same files or modules; neither has started;
  neither is an acceptance, contract or narrowing group; and together they are
  estimated at or under the unit size ceiling.
- **Only unstarted work is ever changed.** A unit that has a branch, a commit,
  a pull request or a step to resume at — or that has finished — is never joined
  to anything and nothing is joined to it. If a unit starts between the plan and
  the write, the join is dropped and the round's other results stand.
- **A unit joined into another ceases to exist.** Its groups are carried by the
  unit before it, and anything that depended on it depends on that unit.
- **Validation refuses a join that breaks a rule,** as it refuses every other
  malformed graph; it does not repair it.
- **A change can opt out.** A task group marked `Separate: <reason>` is never
  joined to another change's unit — for work a person wants to review, or be
  able to revert, by itself.
- **The join is visible:** the plan log says what was joined to what and the
  combined estimate, the unit graph names every change a unit carries, and the
  pull request lists each change and its groups.

## Impact

- **agent-build-kit**: the unit model and everything that reads a unit's change
  and groups (build and review prompts, task ticking, archive readiness, the
  pull request body, the graph), then the planner's prompt and validation.
- No extra agent call: the join is proposed in the planning pass that already
  reads every change in flight.
- Fewer, larger pull requests, up to the existing ceiling. The ceiling is not
  raised.

## Non-goals

- Joining work that has started or finished, or re-cutting units that are
  already built.
- A separate pass that goes looking for joins. They are found when a change is
  planned or re-planned, in the pass that already reads everything in flight.
- Joining across repos or tiers.
- Joining units that are merely both small. Unrelated work in one pull request
  is harder to review and to revert; relatedness is a condition, not a
  tie-breaker.
- Splitting a unit back apart. A joined unit that turns out too large fails the
  way an oversized unit does now, and is fixed in the tasks.
