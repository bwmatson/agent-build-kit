# Tasks

Acceptance: none — the order is decided by `ready_units` over fake units and the status lines over the fake graph the status tests use; no model or host is reached.

Priority: 1

## 1. [agent-build-kit] [unit-test] Ready units start by priority, handoff units break ties, and the status marks them

Done when `ready_units` orders units that have never run by effective priority, then handoff units before the others of equal priority, then effective age, then planned position, with open pull requests and paused builds still first and the room accounting unchanged, `abk status` marks a handoff unit in the ready queue with `(handoff)`, and the documents, the docstrings and the skill say so. Estimate: about 120 changed lines.

- [x] 1.1 Test: in `tests/pipeline/test_ready_handoff_order.py`, with a blocked unit that has work and frees a place, a ready priority-2 prerequisite that has never run and two ready priority-1 units that have never run, `ready_units` returns the two priority-1 units before the prerequisite.
- [x] 1.2 Test: the same file asserts two priority-3 handoff units, an older and a newer, and an older priority-3 unit that is not a handoff unit come out as the older handoff unit, the newer one, then the other; a paused priority-3 unit with work still precedes a priority-1 new unit, handoff or not.
- [x] 1.3 Test: the same file asserts that, at the limit with one blocked unit that has work, a priority-3 handoff unit is returned when no more urgent unit is ready, and that a more urgent unit of a full project is skipped and the handoff unit of a project with room is returned.
- [x] 1.4 Test: in `tests/cli/test_status_handoff_marker.py`, the ready queue prints `2. <unit> (<repo>) — priority 2 (handoff)` for the prerequisite below a priority-1 unit and no marker on any line when no unit is blocked.
- [x] 1.5 In `pipeline/units.py` give `_start_key` the set of handed-off ids and the rank-2 key `(2, urgency, 0 if handed off else 1, age)`, make `ready_units` sort every ready unit with it instead of iterating `[*handoff, *rest]`, and rename `_handoff` to `handoff_units`.
- [x] 1.6 In `cli/pipeline.py` have `_ready_queue_lines` call `handoff_units` on its ready list and append ` (handoff)` after the reason of a unit it returns.
- [x] 1.7 Update the `ready_units` and `handoff_units` docstrings, `docs/architecture.md` (the paragraph on free slots, the handoff text before the classes and the one on new units), `docs/unit-graph.md` (the Priority section: say a handoff unit breaks a tie of equal priority and `abk status` marks it), and the ready-queue line of the `abk-pipeline` skill.
