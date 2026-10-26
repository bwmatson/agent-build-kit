## Why

The priority scale starts at 1, "a bug fix or a fault in the pipeline itself". Sometimes several changes are at priority 1 at once, and a fix that unblocks all of
them has no way to go ahead of them. A person has to lower every other change or wait. The scale needs one value above 1 for the rare work that must go before
all urgent work.

## What Changes

- **`Priority: 0` is accepted** on a group and as a change default. The scale becomes 0 (emergency) to 5 (nice to have). The default stays 3.
- **It orders and inherits like any other value.** A unit of priority 0 starts before a unit of priority 1 within its class, a prerequisite of a priority-0 unit
  has effective priority 0, and a unit with a priority-0 group and a priority-3 group has priority 0. It is a start-first lane only: it does not bypass
  `max_units_in_progress`, `max_concurrent_stacks`, a project's room or any other limit, and it does not stop a running unit.
- **A stored priority 0 is kept.** The store leaves out only the default 3, and nothing reads a stored priority as unset because it is zero.
- **Refusals name the new range.** `6`, `-1` and a value that is not an integer are still errors, and the message now says 0 to 5.
- **Display.** `abk status`, `abk tags` and the graph page show `priority 0` as they show any value other than 3.
- **Text.** The authoring skill says when to use 0 (rare: only for work that must go before all urgent work, such as a fix that unblocks everything), and the
  architecture and unit-graph documents and the changelog give the new scale.

## Impact

- agent-build-kit: `pipeline/work_graph.py` (the value pattern, the error text), `pipeline/units.py` (the `Priority` enum and the bound on `Unit.priority`),
  `pipeline/planner.py` and `pipeline/unit_store.py` (read for zero, with tests), `cli/pipeline.py` and `pipeline/diagram.py` (display, read only), the two
  documents, the `abk-authoring` skill and the changelog.
- Compatible: stored units with priorities 1 to 5 and every existing `tasks.md` read as before. A started unit keeps its priority; a `Priority: 0` added to a
  started unit's change reaches only units that have not started, at the next replan.
- Unrelated to the other changes open at the same time; it needs none of them.
- Priority 1: set by the person who asked for it, so it builds with the other urgent work; nothing is blocked without it.
