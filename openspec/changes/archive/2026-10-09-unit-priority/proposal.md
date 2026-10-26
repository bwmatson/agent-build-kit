# Proposal

## Why

Ready units start in the order they were planned, refined by the age of the stack they unlock. Neither says what matters. A fix
for a fault in the pipeline, or a prerequisite that many other units wait on, queues behind older unrelated work, and a person
who wants a unit sooner has no way to say so short of starting it by hand past the limits. The two ordering rules in preparation
(`start-order-by-stack-age`, `blocked-units-free-their-slot`) would each need their own notion of importance if this were not
settled once.

## What Changes

- **A priority on task groups:** an integer from 1 to 5, 1 the most urgent, 3 for everything that does not say. A
  `Priority: <1-5>` line in a group sets that group's; above the first group it sets the change's default. Anything but an
  integer from 1 to 5 is reported with its line.
- **A unit has the most urgent priority of its groups:** the groups it builds, carried ones included. A unit's effective priority is
  the most urgent among itself and every unit waiting on it, directly or through a chain, so a prerequisite is as urgent as the most
  urgent unit it holds up. The set of waiting units is one shared helper, which the other ordering rules reuse.
- **Priority orders the queue and nothing else:** within each class (an open pull request, a resumed build, a unit that has never
  run) ready units start by effective priority, then by the order the other rules give. It never stops or pauses a running unit,
  never raises the limit on units in progress or the cap on units running at once, and never moves a unit past the class order.
- **A started unit keeps its priority:** editing the file changes only units that have not started. Existing units and changes
  read 3, so nothing changes until a line is written.
- **The status shows it:** the priority of units that are not 3, and the order of the ready queue with the reason.

## Impact

- agent-build-kit: the task-file reader and `abk tags`, the planner, the unit and the store, the choice of ready units, the
  status, the architecture and graph documents, the authoring and pipeline skills.
