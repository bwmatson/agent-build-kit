# Proposal

## Why

`open-pr-ceiling` holds new units back while five pull requests are open. It
counts pull requests, plus builds about to open one. It does not count
started work that has no pull request: a unit paused for the usage window
part-way through its build, one held because its base moved, one that failed
before it pushed. Each of those is a branch that ages, a rebase waiting to
happen, and a person's attention owed — the costs the ceiling exists to bound —
and none of them keeps a new unit from starting.

The unit that matters is the work, not the pull request. A pull request is one
stage a unit passes through; what a person has to carry is every unit that has
been started and not finished. Counting those directly is also simpler to
reason about: "at most five things in flight", not "at most five pull
requests, plus builds heading for one, minus the ones that are satisfied".

## What Changes

- **`limits.max_units_in_progress`, default 5, replaces `limits.max_open_prs`.**
  A unit is in progress from the moment it first starts until it merges, is
  closed or is satisfied: running, in review, being reworked, paused or held
  part-way, failed. A unit that has never started — planned, or planned and
  blocked on a dependency — does not count, and neither does one that is
  merged, closed, satisfied or unplanned.
- **The limit gates starting new work, and nothing else.** At the limit no
  unit that has never started begins. Every unit already in progress carries on
  — a rework, a resume, a restack, a review round, a push, opening its pull
  request — because each of those is how the count goes down, and finished
  work that cannot open its pull request is the outcome this must never
  produce.
- **Failed units count.** A failed unit is started work that needs a person;
  leaving it out would let failures pile up while new work starts on top of
  them. The way to free its place is to requeue it or close it.
- **`max_open_prs` is removed outright**, with no alias. No installation sets
  it yet, so nothing has to migrate.
- **Existing work still goes first** among the units allowed to start, and the
  message a full queue gives names the count, the limit, and what is holding
  the places — so the next action (review, requeue, close) is evident.

## Impact

- **agent-build-kit** only: the readiness rules, the configuration and its
  validation, the tick's and `abk status`'s wording, the docs.
- Behaviour changes only where started work has no pull request: such units
  now hold a place. Everything the ceiling let run still runs.
