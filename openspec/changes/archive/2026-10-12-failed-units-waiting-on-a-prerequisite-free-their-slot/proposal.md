# Proposal

## Why

`blocked-units-free-their-slot` stopped a planned unit that waits on another unit from holding a place. A failed unit still holds one
unconditionally: `in_progress` returns true for running, in review and failed units whatever they wait on. So a failed unit whose
prerequisite has not merged, or whose predecessor is being reworked, failed or held, keeps a place it cannot use. A person only requeues it
once what it waits on is done, so until then the place is dead. Enough of them fill the queue with units that cannot move, and the work they
wait on is kept from starting; the way out so far has been to raise `limits.max_units_in_progress` by hand, which only hides the next clog.

The archived change left a failed unit counting on purpose ("until it is requeued and finishes, or is closed"), because a failed unit is
stopped work a person has to look at. That holds for a failed unit that can be requeued now. It does not hold for one that is waiting: it
cannot run whoever looks at it.

## What Changes

- **A waiting failed unit does not count:** a `failed` unit for which `waiting_on(unit, graph)` is non-empty is not in progress while it
  waits, and counts again from the moment the wait ends. A failed unit with no such wait counts exactly as now.
- **Nothing else about it changes:** it stays `failed` (state, branch, pull request, feedback and thread untouched), is never requeued
  automatically, and a person still requeues it with `abk requeue`.
- **The status and the graph say so:** `failed, waiting on <units>`; the full-queue report leaves it out of the units holding places and
  says how many failed units waiting are not counted, as it does for blocked ones.
- **Stated in terms of `waiting_on` alone,** so it holds before and after `needs-start-on-the-parents-branch` rewrites `waiting_on`.

## Impact

- agent-build-kit: the count of units in progress, `uncounted`-style reporting of the units not counted, the queue line, the status, the
  graph label, the architecture document, the configuration document, the graph document, the pipeline and config skills, the changelog.
- Spec: `unit-scheduling` (modifies two requirements, adds one).
