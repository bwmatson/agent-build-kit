# Proposal

## Why

A planned unit with a branch or a run log counts as in progress however it got there. Four units sat planned, each waiting on a
prerequisite or a predecessor, and between them with two running units they made the queue full. The prerequisite they all waited on
could not start because the limit was reached by their own places, and nothing else was making progress. The order in which free
places are given (`start-order-by-stack-age`) does not help: it cannot give a place that is not free.

## What Changes

- **A blocked unit does not count:** a planned unit that waits on another unit, however much work it has, is not in progress while it
  waits. It counts again when it is no longer blocked.
- **The unit that blocks it takes its place:** before the usual classes, a ready prerequisite of a blocked unit that would otherwise
  count starts into that unit's place, one place for each blocked unit and one unit for each place. The limit and the cap on units
  running at once still hold, and the effective age order still applies to everything else.
- **An unblocked unit waits for room:** a planned unit that stops being blocked starts only while the number of other units in
  progress is below the limit. A unit paused by a usage pause, not blocked, resumes at the limit as before.
- **The status says so:** it counts the blocked units that are not counted and lists what each waits on, and the graph shows them as
  blocked.

## Impact

- agent-build-kit: the count of units in progress, the choice of ready units, the status and the queue line, the graph label, the
  architecture document, the graph document and the pipeline skill.
