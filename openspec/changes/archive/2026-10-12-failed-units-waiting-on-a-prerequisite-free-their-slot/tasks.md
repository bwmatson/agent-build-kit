# Tasks

Acceptance: none — the count and the reports are pure over a unit graph; tier-1 tests prove each case and nothing a consumer drives changes.

Priority: 2

## 1. [agent-build-kit] [tier1] A failed unit waiting on another unit does not hold a place

Done when a failed unit that `waiting_on` another unit is not counted in progress while it waits and is again when it does not, the full-queue
report and the status say so, and the graph reads `failed, waiting on <units>`.

- [x] 1.1 Test: `in_progress` is false for a failed unit whose same-repo predecessor is not yet reviewed (planned, running, being reworked,
      failed or held), whose cross-repo dependency has not merged and whose `Needs:` gate has not merged, and true for a failed unit
      whose predecessor is in review or merged, and for one with no dependency; `start_room` rises by one for each waiting failed unit.
- [x] 1.2 Test: a failed unit that waits counts again, with the state still `failed`, once the prerequisite is reviewed or merged; the unit's
      state, branch, pull request and history are the same before and after, and no tick requeues it.
- [x] 1.3 Test: with the limit reached by a waiting failed unit and other units, a planned unit that has never started starts into the place;
      then the wait ends and `ready_units` starts nothing for the failed unit, a rework, resume, restack and push still proceed with the
      count over the limit, and a planned unit no longer blocked stays planned until the count is below the limit.
- [x] 1.4 Test: `max_concurrent_stacks` and the depth cap choose the same units with a waiting failed unit in the graph as without it; a
      held unit does not count whether or not it waits; a ready prerequisite of a waiting failed unit gets no handoff and follows the
      usual order, while a blocked planned unit's prerequisite still does (the existing handoff tests stay green).
- [x] 1.5 Test: the queue line leaves a waiting failed unit out of its count and its by-state list, ends with "N failed waiting not counted"
      beside the blocked count, and a failed unit that does not wait is still listed as failed among the units holding the places.
- [x] 1.6 Test: the status prints `failed, waiting on <ids>` for a waiting failed unit and keeps its `failed:` line; the graph label of
      that unit reads `failed, waiting on <ids>` and its class is `failed`; a failed unit that does not wait is labelled `failed`.
- [x] 1.7 Update the tests that state the old rule: in `tests/pipeline/test_units_in_progress.py` keep `test_a_failed_unit_holds_a_place` and
      the four-started-units test for a failed unit that does not wait, and name it so in the title; in
      `tests/pipeline/test_blocked_units.py` make `test_running_review_and_failed_units_count_and_a_held_unit_does_not` say the failed
      unit has no wait. Write the new graphs with `waiting_on`, `blocked` and `failed_waiting` only, never `merge_before` or `unmet_gates`.
- [x] 1.8 Add `failed_waiting(unit, graph)` and `failed_waiting_units(graph)` beside `blocked` and `uncounted` in `pipeline/units.py`,
      leave `uncounted` and `_handoff` as they are, and make `in_progress` return false for a failed unit that waits.
- [x] 1.9 Report the waiting failed units: the count after the blocked count in `_queue_full_line`, a line for each in the status beside
      `_blocked_lines`, and the label in `pipeline/diagram.py`; `effective_state`, the pull request labels and the web page stay as they are.
- [x] 1.10 Update `docs/architecture.md` (the paragraph on `limits.max_units_in_progress`), the `max_units_in_progress` comment in
      `docs/configuration.md` and the `abk-config` skill's `limits:` block, the "Blocked units" row of `docs/unit-graph.md`, the queue-full
      step of the `abk-pipeline` skill, and add one changelog bullet under `## Unreleased` as `AGENTS.md`'s Changelog section says.
