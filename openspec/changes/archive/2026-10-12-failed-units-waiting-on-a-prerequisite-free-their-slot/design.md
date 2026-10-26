# Design

## What was checked, and where

Read-only against the agent-build-kit checkout; paths are under `src/agent_build_kit/` unless they name `tests/` or `docs/`.

- `pipeline/units.py`: `in_progress` returns false for merged, closed, satisfied and held units, true for running, in review and failed units
  with no look at the graph, and otherwise `_worked_on(unit) and not blocked(unit, graph)`. `blocked` is `unit.state == PLANNED and
  bool(waiting_on(unit, graph))`. `uncounted(graph)` lists the blocked units with work and is the set `_handoff` frees places for.
  `_waits_for_room` is true only for a `PLANNED` unit. `start_room` and `ready_units` count `in_progress(unit, graph)` (minus
  `_waits_for_room` in `ready_units`).
- `pipeline/units.py` `waiting_on`: a same-repo parent must be in `REVIEWED`, a cross-repo one merged, a `merge_before` entry merged; a
  predecessor reworking, failed or held holds the unit. It does not look at the unit's own state, so it already answers for a failed unit.
- `cli/pipeline.py`: `_queue_full_line` builds "queue is full: N units in progress, limit M (<count> <label>, ...)" from the units
  `in_progress` accepts, labelled by `in_progress_label`, then appends "; K blocked not counted" from `_blocked_lines`, which prints
  `  blocked: <id> (<repo>) waits on <ids>` for each `uncounted` unit. The status prints a failed unit as `  failed: <id> (<repo>) at <step> — <note>`
  and, if units wait on it, `_blocked_by`'s "requeue it with `abk requeue`". `_nothing_started_reason` reuses `_queue_full_line`.
- `pipeline/vocabulary.py` `effective_state` returns `unit.state` for every state but running, in review and planned, so a failed unit is
  always drawn `failed`; only a planned unit becomes `blocked`. `pipeline/diagram.py` writes `STATES[state].name` into the node label.
  `pipeline/labels.py` and `serve/server.py` read the same function.
- Tests: `tests/pipeline/test_units_in_progress.py` (`test_started_work_counts_as_in_progress`, `test_a_failed_unit_holds_a_place`,
  `test_with_four_started_units_one_failed_...`), `tests/pipeline/test_blocked_units.py`
  (`test_running_review_and_failed_units_count_and_a_held_unit_does_not`), `tests/cli/test_blocked_status.py` (a failed prerequisite and a
  waiter), `tests/cli/test_tick_environment_cause.py` (the queue line names units waiting for the environment).
- Docs: `docs/architecture.md` (the paragraph on `limits.max_units_in_progress`: "running, in review or failed"), `docs/configuration.md`
  (the `max_units_in_progress` comment), `docs/unit-graph.md` (the "Blocked units" row), the `abk-pipeline` skill (the queue-full step) and
  the `abk-config` skill (its `limits:` block).

No test I found pins a failed unit that waits as counted: every failed unit in these tests has no unmet dependency, and each one stays
valid. UNVERIFIED: that no other test builds a failed unit with a dependency and asserts it counts; the builder greps `tests/` for `FAILED`
and `failed` next to `depends_on`, `start_room`, `in_progress` and `queue is full` and updates what it finds.

## The rule

`in_progress` returns false for a `FAILED` unit when `waiting_on(unit, graph)` is non-empty, and true otherwise, as today. The rule reads
`waiting_on` and nothing else: not `merge_before`, not `unmet_gates`, not a cause. A waiting failed unit is not "blocked": `blocked` stays
a predicate on planned units, and a new predicate, `failed_waiting(unit, graph)` (`unit.state == FAILED and bool(waiting_on(unit, graph))`),
names this one. It is derived from the units each time, as `blocked` is; no stored state, no new cause, no migration.

Which waits count is whatever `waiting_on` says, so it matches what the graph and the scheduler already treat as a wait: a `Needs:` gate
whose dependency has not merged, a same-repo predecessor not yet reviewed or merged, a cross-repo dependency not merged, and a
predecessor being reworked, failed or held. A failed unit whose predecessor is in review or merged has no wait and counts.

`in_progress` gets one more line, ahead of the running/in-review/failed line: a failed unit counts unless it is waiting. The graph
argument already exists and defaults to `()`, with which a unit waits on nothing, so the call sites that pass no graph keep today's answer.

## It stays failed

The change reads `waiting_on`; it writes nothing. State, branch, pull request, feedback, thread and history are untouched, so `abk requeue`,
`_blocked_by` ("N units waiting on it") and the failed-step note read as before. Nothing requeues the unit when its wait ends: it counts
again, still `failed`, and a person requeues it. `no auto-retry for stopped jobs` stays true.

## Interactions

**(a) The caps.** `max_concurrent_stacks` counts `RUNNING` units and `stack_depth_build_cap` and the rebase cap read depth and parents;
neither calls `in_progress`, and a failed unit is neither running nor a builder of anything. They are unaffected. Only `start_room` and the
room in `ready_units` change, because they sum `in_progress`.

**(b) `_waits_for_room` and the limit.** A failed unit is never planned, so `_waits_for_room` (planned, worked on, no pull request, a cause
or a parent that went back) is false for it and stays so. When a failed unit's wait ends, nothing starts it, picks it before another unit
or gives it priority: it is not in `ready_units`' candidates (`state != PLANNED`), and it is not given a place; it only counts again in the
sum, so the room for new units falls by one. If that takes the count over the limit, the limit only stops new starts, exactly as "Work
already in progress continues at the limit" says: a rework, a resume, a restack and a push proceed, and a planned unit that was blocked and
no longer is waits for room. Nothing already running is stopped, so the count can briefly exceed the limit, as it can today when a rework
is sent back. A unit that was handed a place by `_handoff` is not displaced.

**The handoff is unchanged.** `_handoff` frees a place for each `uncounted` unit, which stays the blocked planned units with work. A
waiting failed unit gives up its count but not a handoff: a ready prerequisite of a failed unit gets no priority over the usual order,
because the unit will not run until a person requeues it, so nothing needs its prerequisite sooner than the effective age already puts it.
The freed room goes to units in the usual order. A separate listing, `failed_waiting_units(graph)`, serves the report and keeps
`uncounted` as the handoff's set.

**(c) `needs-start-on-the-parents-branch`** (planned, unstarted). Its group 3 removes `merge_before` and rewrites `waiting_on` and
`unmet_gates`. This change is written purely in terms of `waiting_on(unit, graph)`, so it holds before and after that rewrite: whichever
units `waiting_on` names then, a failed unit waiting on them does not count. The tests build a graph with a failed unit and a not-merged
prerequisite and call `waiting_on`, `failed_waiting` and `in_progress`, never `merge_before`, `unmet_gates` or the `merged` qualifier, so
they survive it. The report prints `waiting_on`'s units and does not name a gate. **No `Needs:` is required** in either direction: the
change does not touch what that one rewrites, and whichever lands first, the other's tests keep passing. UNVERIFIED: that no helper that
change keeps still reads `merge_before` in `in_progress`'s path; this change adds none.

**(d) `tier2-failures-in-untouched-tests-are-fixed-once`.** It parks a unit as `planned` with the cause `gated` until a fix change merges.
That is a planned unit, already covered by `blocked`; a failed unit never takes that route. No conflict. If a failed unit is requeued while
that gate is unmet it becomes planned and gated, and `blocked` takes over from this change.

**(e) Held.** A held unit does not count and stays uncounted whatever it waits on; this change does not touch that branch, which comes
first in `in_progress`. A unit waiting and then held does not count either way, and one released to `failed` is judged by the rule above.

## Reporting

The full-queue line lists the units holding the places, so a failed unit that waits is left out of its total and its by-state counts
(`in_progress` is the filter), and it adds "; K failed waiting not counted" after the blocked count. It never names a failed waiting unit as
holding a place. The status adds one line for each: `  failed, waiting on <id>, <id>: <unit> (<repo>)`, beside the existing `failed:`
line, which stays as it is. The units a failed unit waits on are `waiting_on`'s, as ids, as `blocked:` prints them; the report says "units",
not groups, as that line does. The failed unit with an environment cause is "waiting for the environment" only while it counts; one that
also waits on a unit is reported as failed waiting.

## The graph

`effective_state` keeps returning `failed`, so the node keeps its class, colour and thick outline, the pull request's `failed` label and
the web page's status. Only the node's label changes: `pipeline/diagram.py` writes `failed, waiting on <ids>` in place of `failed` for a
unit that is `failed_waiting`, the way a blocked unit is shown by its own name. A state the web UI and `labels.py` have not heard of is
not introduced. UNVERIFIED: whether the web page (`serve/server.py`) should also show the wait; it receives the same `failed` status and
is left alone, and a later change can add it.

## Docs

`docs/architecture.md` says "running, in review or failed"; it gains the waiting exception and a pointer to `waiting_on`.
`docs/configuration.md`'s `max_units_in_progress` comment says what counts and is brought in line. `docs/unit-graph.md`'s "Blocked units" row
names failed units. The `abk-pipeline` skill's queue-full step ("or when a failed unit is requeued ... and finishes, or is closed") and
the `abk-config` skill's `limits:` block are updated, and the changelog gets one entry.

## Related changes

`blocked-units-free-their-slot` (archived): this extends it, and the sentence in its spec that a failed unit counts until requeued is
narrowed here. `start-order-by-stack-age` and `unit-priority` are unaffected. `no auto-retry` (a standing rule) holds.
