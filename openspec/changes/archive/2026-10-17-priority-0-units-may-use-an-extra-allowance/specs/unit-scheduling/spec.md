## RENAMED Requirements

- FROM: `### Requirement: Priority 0 starts first and bypasses no limit`
- TO: `### Requirement: Priority 0 starts first and may use the emergency lane`

## MODIFIED Requirements

### Requirement: Priority 0 starts first and may use the emergency lane

Priority 0 SHALL be the most urgent value. A unit of effective priority 0 SHALL start before a ready unit of effective priority 1 or less urgent in the
same class, with ties and classes ordered as for any other value. It SHALL NOT start a unit that is not ready and SHALL NOT stop a running unit. Its only difference from any other value
in what may start is the emergency lane (the requirement of that name): it SHALL NOT otherwise bypass or raise the limit on units in progress, the cap on units running at once, a
project's room, the usage guard, the depth cap, a dependency, a lease, a backoff or any other limit. `abk status`, `abk tags` and the graph page
SHALL show `priority 0` as they show any priority other than 3.

#### Scenario: Priority 0 goes before priority 1

- **GIVEN** one place is free and two ready units that have never run, the later planned of priority 0 and the other of priority 1
- **WHEN** units are chosen
- **THEN** the priority-0 unit starts first

#### Scenario: A prerequisite of a priority-0 unit goes first

- **GIVEN** a ready priority-3 unit that a priority-0 unit waits on, and an older ready priority-1 unit that nothing waits on
- **WHEN** units are chosen with one free place
- **THEN** the prerequisite starts first

#### Scenario: A full queue still holds a priority-0 unit

- **GIVEN** the limit on units in progress is reached and `emergency_extra` is 0, or the project's emergency lane cap is all in use
- **WHEN** a ready unit of priority 0 is considered
- **THEN** it does not start, and it starts first when a place frees

#### Scenario: A full queue does not hold a priority-0 unit that the lane admits

- **GIVEN** the limit on units in progress is reached and `emergency_extra` is 1 with no unit in the lane
- **WHEN** a ready unit of priority 0 is considered
- **THEN** it starts in the emergency lane, as the requirement of that name says

#### Scenario: The display shows priority 0

- **GIVEN** a unit of priority 0 in the store, and a group of priority 0 in a change
- **WHEN** `abk status`, `abk tags` and the graph page are shown
- **THEN** each says `priority 0` for it

## ADDED Requirements

### Requirement: A priority-0 unit starts as soon as it is ready, in its own lane with its own cap

For a project, a ready planned unit that is drawing on room (it has never started, or it was blocked, is not now and waits for room) and whose effective priority is 0 SHALL start at the next
tick even when the limit on units in progress and the cap on units running at once are full, after the usage guard, the depth cap, dependencies, leases, backoff and held splits have been
applied. A unit that fits inside the normal limits SHALL start normally and SHALL NOT use the lane cap. Otherwise it SHALL start in the emergency lane when the project's lane use is below
`project_limits.emergency_extra`; the lane use SHALL be the number of priority-0 units currently using the lane (started past the normal limits and not finished), read with the units already
chosen in the round, and SHALL NOT be judged on the occupancy margin. A unit SHALL stay in the lane until it finishes. The lane SHALL be independent of the restack lane: a priority-0 start
SHALL NOT be blocked by lane runs or use any of the restack lane's cap, and lane runs SHALL NOT be blocked by priority-0 units. Every other unit SHALL see the normal limits. The lane SHALL NOT be a
quota or a reservation of a place or a worker. It SHALL be counted for each project. A unit started in the lane SHALL count as in progress and as running like any other. A unit already
in progress (a rework, a resume, a review round) SHALL be unaffected. A priority-0 unit that waits on a dependency is not ready and SHALL use nothing. With `emergency_extra` 0 the rules
SHALL be those without the lane. (The occupancy is today the builds in flight and the units stored running; once the restack lane's occupancy is built it is that figure, and the priority-0
units are part of it.)

#### Scenario: A ready priority-0 unit starts at a full queue and full workers

- **GIVEN** a project with `max_units_in_progress` 5 and `max_concurrent_stacks` 4, five units in progress of which four are running, and `emergency_extra` 1
- **WHEN** a ready priority-0 unit that has never started is considered at the next tick
- **THEN** it starts, and the project has six units in progress and five running

#### Scenario: A ready priority-1 unit does not start in it

- **GIVEN** the same project, with a ready priority-1 unit that has never started and no priority-0 unit
- **WHEN** units are chosen
- **THEN** it does not start, and its wait reason is `queue_full`

#### Scenario: Two priority-0 units with a lane cap of 1

- **GIVEN** the same project and two ready priority-0 units that have never started
- **WHEN** units are chosen
- **THEN** the first in start order starts and the other waits for the lane cap with the reason `queue_full`, and it starts when the first finishes or when the project is below the normal limits

#### Scenario: A lane cap of 0

- **GIVEN** the same project with `emergency_extra` 0
- **WHEN** a ready priority-0 unit is considered
- **THEN** it does not start, exactly as without this requirement

#### Scenario: A priority-0 unit inside the normal limits does not use the lane cap

- **GIVEN** a project with four units in progress of five and one running of four, `emergency_extra` 1, and two ready priority-0 units
- **WHEN** units are chosen
- **THEN** the first starts normally (five in progress) and does not use the lane cap, and the second starts in the lane

#### Scenario: A prerequisite of a priority-0 unit uses the lane

- **GIVEN** a ready priority-3 unit that a priority-0 unit waits on, at the same full project
- **WHEN** units are chosen
- **THEN** the prerequisite starts in the lane and the priority-0 unit stays blocked and uses nothing

#### Scenario: A unit already started is unaffected

- **GIVEN** a full project and a priority-0 unit with a pull request sent back for rework, and a paused priority-0 unit with a branch
- **WHEN** units are chosen
- **THEN** the rework runs as it does at any limit, and the paused unit waits for a normal worker and does not use the lane

#### Scenario: A lane run and a priority-0 start do not block each other

- **GIVEN** four builds running at a cap of four, a moved-base run in the restack lane, `emergency_extra` 1 and a ready priority-0 unit
- **WHEN** units are chosen, and then a base moves while the priority-0 unit runs
- **THEN** the priority-0 unit starts at once, the lane run is admitted at once, neither uses the other's cap, and both count toward occupancy (6/4)

#### Scenario: Other limits still apply

- **GIVEN** a ready priority-0 unit that is beyond the depth cap, under a lease, in a backoff, waiting for a held split, or refused by the usage guard
- **WHEN** units are chosen
- **THEN** it does not start, the lane admitting nothing those rules refuse

### Requirement: A unit in the emergency lane counts toward occupancy and no ordinary new unit starts meanwhile

A unit in the emergency lane SHALL count as in progress and as running, and so toward the project's occupancy, which MAY read above the cap. While the project's count is at or above
`max_units_in_progress` or its occupancy is at or above the cap, no never-started unit that is not of effective priority 0 SHALL start. The lane's unit takes extra room and SHALL NOT make
any, so ordinary starts SHALL wait until the figures fall below the normal limits. A unit that waits for this SHALL read `queue_full` or `slot` as it does for a full queue.

#### Scenario: Nothing else flows in

- **GIVEN** a priority-0 unit started in the lane at a full project, five builds running at a cap of four, and a ready priority-1 unit
- **WHEN** a normal build finishes and units are chosen
- **THEN** the priority-1 unit does not start, because the occupancy is still four, and it starts once the occupancy is below four

### Requirement: A priority-0 unit never holds back a unit that is finishing

A priority-0 start SHALL NOT delay any unit already in progress. A rework, a resume, a review round, a restack and a unit finishing its review SHALL continue as without the lane; a resume SHALL
be held to the free workers counted without the priority-0 units in the lane, so the lane's workers are never a reason for a unit that is finishing to wait.

#### Scenario: A rework is not delayed

- **GIVEN** a priority-0 unit running in the lane at a full project and an in-progress unit sent back for rework
- **WHEN** units are chosen
- **THEN** the rework runs at once

#### Scenario: A resume does not wait for the lane

- **GIVEN** three normal builds and one priority-0 unit in the lane at a cap of four, and a paused unit with a branch
- **WHEN** the round resumes units
- **THEN** the paused unit is resumed as with three builds and no lane unit

### Requirement: The build pool has a thread for the emergency lane

The pool that runs a pass's builds SHALL have `max_concurrent_stacks + emergency_extra` threads for each project that can build, so that a unit started in the lane runs at once and takes no thread
from a unit that is finishing. The restack lane SHALL keep its own workers, apart from the pool, and SHALL add nothing to its size. The number of units that start SHALL be decided by the round,
never by the size of the pool, and a pool larger than the cap SHALL start no unit that would not start without it.

#### Scenario: The extra worker runs

- **GIVEN** four builds in flight at a cap of four and `emergency_extra` 1
- **WHEN** a ready priority-0 unit starts in the lane
- **THEN** its build runs at once beside the four, not queued behind one

### Requirement: The status shows the emergency lane

When a project's room is full or the lane is in use, `abk status` SHALL show it. A queue-full line SHALL say a priority-0 unit may still start while the project's lane use is below
`emergency_extra`, which is above 0. A line `emergency room N/M used by <unit>` SHALL be printed for a project whose lane is in use, N the lane use (the lane cap in use, not a margin) and M
`emergency_extra`, naming the units in the lane. The ready queue SHALL mark `(emergency room)` after the reason of a unit that starts only in the lane, and SHALL NOT change the order or the reason
shown. The unit's wait reason SHALL be `queue_full` for a never-started unit that finds no room. The sample row SHALL keep the normal `limit` and `cap`, and one gauge
`abk.slots.emergency_used` SHALL report the lane use summed over the projects. With `emergency_extra` 0 nothing SHALL be printed or marked for it.

#### Scenario: The lane is free

- **GIVEN** a full queue, `emergency_extra` 1 and no unit in the lane
- **WHEN** the status is read
- **THEN** the queue-full line says a priority-0 unit may still start and no emergency-room line is printed

#### Scenario: The status shows the lane

- **GIVEN** a full queue with one priority-0 unit started in the lane
- **WHEN** the status is read
- **THEN** a line `emergency room 1/1 used by <unit>` is printed beside the queue-full line, which no longer says a priority-0 unit may still start

#### Scenario: A restack run does not use the lane cap

- **GIVEN** four builds and a moved-base run in the restack lane, `emergency_extra` 1
- **WHEN** the status is read
- **THEN** no emergency-room line is printed and the queue-full line says a priority-0 unit may still start

#### Scenario: The ready queue marks the unit

- **GIVEN** a full queue with a ready priority-0 unit that would start only in the lane and a priority-1 unit behind it
- **WHEN** the status is read
- **THEN** the ready queue lists the priority-0 unit first with `(emergency room)` after its reason, and the priority-1 unit without a marker

#### Scenario: Lane 0 prints nothing

- **GIVEN** `emergency_extra` 0
- **WHEN** the status is read
- **THEN** no emergency-room line or sentence appears and the queue-full line reads as before

#### Scenario: The sample row and gauge

- **GIVEN** five builds in a project at a cap of four after a start in the lane
- **WHEN** a pass refreshes
- **THEN** the sample row has `running` 5, `cap` 4 and `free_workers` 0, and `abk.slots.emergency_used` is 1
