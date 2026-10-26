# Tasks

Acceptance: none — the order and the parsing are pure over task files and a unit graph; tier-1 tests prove each case.

## 1. [agent-build-kit] [tier1] A group carries a priority, a unit stores it, and who waits on a unit is one question

Done when a group can carry a priority, a unit stores the most urgent of its groups, and one helper answers which units wait on a
unit.

- [x] 1.1 Test: `Priority:` in a group sets the group's priority, above the first group it sets the change's default, a group's
      own line wins, and the default is 3; a value outside 1 to 5, a non-integer, a second line in one place and a line outside any
      group or head are errors with their line; `abk tags` lists a priority that is not 3.
- [x] 1.2 Test: the waiting set follows chains, crosses repos, skips merged, closed and satisfied units and looks through
      satisfied ones, gives a prerequisite of two units both, does not loop on a cycle and leaves out the units it is told to
      exclude.
- [x] 1.3 Test: a unit of several groups, carried ones included, takes the smallest; a prerequisite takes the priority of the most
      urgent unit waiting on it and no less urgent than its own; a prerequisite of only priority-5 units is not made more urgent.
- [x] 1.4 Test: a unit that has started keeps its priority when the file changes and an unstarted one takes the new one, a store
      record without the field reads 3, a unit at 3 is written without the field and one at another value round-trips; a
      record with a priority is refused, with the usual message, by the check an older release applies to an unknown field.
- [x] 1.5 Add the priority type and the field on `Unit`, the line in `work_graph.py` with its errors and `abk tags` listing, the
      priority set by the planner from each member's groups, `waiting_on_me` in `units.py`, and the store's omission of the default
      and its keeping of a started unit's priority.
- [x] 1.6 Update `docs/architecture.md`, the authoring skill (the scale and what its numbers mean) and `docs/unit-graph.md`, and add a
      changelog entry.

## 2. [agent-build-kit] [tier1] The priority and the order are shown

Done when the status and the graph show each unit's priority and the order of the ready queue with the reason for it.

- [x] 2.1 Test: `abk status` marks units whose priority is not 3, prints the ready queue in the order the scheduler chose with the
      reason for each position, and the graph shows a badge.
- [x] 2.2 Add the status and graph display. The sort itself, by (effective priority, effective age, planned position), is written
      with the age order in `start-order-by-stack-age`, which reads the field and the helper from group 1; this group only shows it.
- [x] 2.3 Update `docs/unit-graph.md` and the pipeline skill, and add a changelog entry.
