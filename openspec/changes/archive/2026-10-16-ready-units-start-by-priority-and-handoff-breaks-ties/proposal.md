## Why

The scheduler offers handoff units (ready units that have never run and take the place a blocked unit frees) ahead of every other ready unit, whatever
their effective priority, while all other units are sorted by rank, priority and age. In a real queue a priority-2 handoff unit stood first, ahead
of two priority-1 units that had never run. Priority is meant to be the main order among new units; the handoff rule should break ties, not override it.

## What Changes

- **Among units that have never run** the order becomes effective priority, then handoff units before the others of equal priority, then effective
  age, then planned position. A handoff unit no longer outranks a more urgent unit.
- **Rank stays first**: open pull requests, then paused builds with work, then new units. Only units that have never run can be handoff units, as now.
- **Room accounting is unchanged.** Only the order in which candidates are offered changes. A less urgent handoff unit still gets the freed place when
  nothing more urgent is ready or the more urgent ones are skipped by the room, worker or depth limits. There is no reserve and no preemption.
- **`abk status`** marks a handoff unit in the ready queue with `(handoff)`.
- The documents, the docstrings and the `abk-pipeline` skill describe the new order.

## Capabilities

### Modified Capabilities

- `unit-scheduling`: the ordering requirement "Free slots go to existing work first, within the limit" changes; a requirement for the status marker is added.

## Impact

`pipeline/units.py` (`_start_key`, `_handoff`, `ready_units`), `cli/pipeline.py` (`_ready_queue_lines`), `docs/architecture.md`, `docs/unit-graph.md`,
the `abk-pipeline` skill. No stored data, command or setting changes.
