# Proposal

## Why

When a place in progress frees, the pipeline starts the ready unit that was planned first among those that have never run. A unit
that other units are waiting on is not treated differently from one that unlocks nothing. Two units sat gated and idle, each
holding a place, waiting on a prerequisite that had been ready for hours, and the places that freed went to newer units that
nothing was waiting for. The prerequisite then could not start because the limit was reached by the places its own waiters held.
Nothing named a failed prerequisite either: the status said only that nothing was ready to build.

## What Changes

- **Units that have never run start in order of their stack's age:** each ready unit takes the age of the oldest unit among itself
  and every unit that waits on it, directly or through a chain, and starts in that order, oldest first, with ties going to the
  unit's own planned position. A prerequisite of a really old unit goes ahead of newer work. A prerequisite of only newer units
  does not take an older unit's place. Depth and the number of waiting units do not matter.
- **Priority comes first:** the order is (effective priority, effective age, planned position), with the effective priority
  defined by `unit-priority`, so a prerequisite of a priority-1 unit goes ahead of an older priority-3 one. The set of waiting
  units is that change's shared helper, not a second one built here.
- **Work already in progress is not affected:** a unit with an open pull request and a build resumed after a pause or hold start
  first, as now, and the limit on units in progress is never exceeded.
- **A failed prerequisite is named:** when a failed unit has units waiting on it, the status and the reason nothing was started
  say so, with how many wait and that it needs a requeue.

## Impact

- agent-build-kit: the order in which ready units are chosen (after `unit-priority`), the status and the reason given when nothing starts, the architecture
  document and the pipeline skill.
