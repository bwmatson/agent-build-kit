## ADDED Requirements

### Requirement: A restack takes no build slot and no start admission

Moving a unit onto a changed base SHALL run in a lane of its own, outside the workers that build units. It SHALL NOT take a place in
`max_concurrent_stacks`, SHALL NOT be reduced by the builds running, SHALL NOT delay a build, and SHALL NOT be admitted by the limit on
units in progress: the unit it moves is already in progress or already not, and moving it is not a start. The work that follows a move (the
re-verify, the review of a resolved move, the push of a rewritten head, the rework, and the port of a conflict the resolver could not
settle) SHALL be the unit's own build and SHALL run in a build worker as before.

#### Scenario: Every build slot is busy

- **GIVEN** every build slot is taken by a build and a parent merges, so a child's branch must move onto its new base
- **WHEN** the merge is seen
- **THEN** the child's restack runs at once, and no build is stopped, delayed or given up for it

#### Scenario: A restack running does not reduce the free workers

- **GIVEN** a pass with one free build slot and a restack running in the lane
- **WHEN** the pass samples its slots
- **THEN** the sample's free workers is one, and a unit that is ready starts in that slot

#### Scenario: A unit at the limit on units in progress

- **GIVEN** the number of units in progress is at the limit and a unit already in progress has a moved base
- **WHEN** the unit is restacked
- **THEN** it is moved, and no admission is asked of the limit

### Requirement: A restack starts when it is seen

A restack SHALL start when the pipeline sees that a unit's base moved, and SHALL NOT wait for the next tick or for a build slot. The base
SHALL be seen by the merge, release and depth handlers when the poller reports the event, by a scan after every poll, every finished
build, every finished restack and every usage pause, and by the end of a run that left its unit planned for a moved base. The scan SHALL
find every unit owed a restack: one that is planned, running with a parked thread, or in review, whose cause is a moved base or a deferred
restack, whose branch does not hold its base, that no run holds, that is not waiting on another unit, and that is not planned for a restack
conflict. A restack that could start when a lane worker is free SHALL start before the handler that saw it returns; one that cannot SHALL
start when a worker is free. A unit SHALL be queued at most once, and its new base SHALL be read when its move starts.

#### Scenario: A merge is seen

- **GIVEN** a parent whose pull request has merged and a child stacked on it
- **WHEN** the poller reports the merge
- **THEN** the child's move starts without waiting for a tick

#### Scenario: A unit planned for a moved base

- **GIVEN** a unit a run left planned with a moved base, and no run holding its branch
- **WHEN** the run ends
- **THEN** the unit is moved without waiting for a build slot

#### Scenario: A unit deferred, found by the scan

- **GIVEN** a unit planned with a deferred restack whose branch does not hold its base
- **WHEN** a scan runs after a poll
- **THEN** it is moved

#### Scenario: A unit whose branch already holds its base

- **GIVEN** a unit planned with a deferred restack because its resolved move changed its diff, whose branch holds its base
- **WHEN** a scan runs
- **THEN** it is not restacked again, and waits for its review as before

#### Scenario: A conflict the resolver could not settle

- **GIVEN** a unit left planned for a restack conflict
- **WHEN** a scan runs
- **THEN** it is not restacked again, and its next run does the port

#### Scenario: A unit waiting on another unit

- **GIVEN** a planned unit that waits on a unit that has not merged
- **WHEN** a scan runs
- **THEN** it is not restacked, and is restacked once it is no longer waiting

#### Scenario: A unit owed a restack is not started for it

- **GIVEN** a unit owed a restack while a build slot is free
- **WHEN** the pass looks for what to start
- **THEN** the slot is not given to the unit for its move, and it is started for its build once the lane has moved it

### Requirement: A separate cap bounds how many restacks run at once

The workspace SHALL configure `limits.max_concurrent_restacks`, the most restacks that run at once across every repository, defaulting to
2. It SHALL be a positive integer, and a value that is not one SHALL be refused when the configuration is loaded, naming the setting. A
restack beyond the cap SHALL wait in the order it was seen, and SHALL start the moment another finishes. The cap SHALL be separate from
`max_concurrent_stacks` and from `max_units_in_progress`.

#### Scenario: A burst of merges

- **GIVEN** the cap is 2 and five merges are seen together, each with a child to move
- **WHEN** the lane takes the work
- **THEN** two restacks run, three wait in the order they were seen, and each starts as one finishes

#### Scenario: The default

- **WHEN** an installation sets no `max_concurrent_restacks`
- **THEN** the cap is 2

#### Scenario: A value that is not a positive integer

- **WHEN** the setting is 0, negative or not an integer
- **THEN** the configuration is refused, naming `max_concurrent_restacks`

#### Scenario: One unit named twice

- **GIVEN** a unit queued for a restack
- **WHEN** a second event names it before it starts
- **THEN** it is queued once, and moves onto the base it has when it starts

### Requirement: A restack never runs under a running step, and a branch is restacked once at a time

A restack SHALL take the unit's branch claim before it does anything, so that no restack runs on a branch a run holds and no two restacks
run on one branch. A unit whose step is running SHALL NOT be restacked: a build that finds its base rewritten SHALL stop at its next
boundary as before, and be moved afterwards. A restack that finds the branch held SHALL leave the unit as it was, and SHALL be tried again
after the holder's run ends. A restack SHALL take the repository's turn for the phases the sibling requirement on restacks names, and SHALL
NOT hold it while an agent edits files.

#### Scenario: A step is running

- **GIVEN** a unit whose build is running a step when its base moves
- **WHEN** the move is seen
- **THEN** nothing is rebased under the step, the build stops at its next boundary, and the unit is then restacked

#### Scenario: Two restacks of one branch

- **GIVEN** a restack running on a branch
- **WHEN** another event names the same unit
- **THEN** no second restack starts on the branch until the first ends

#### Scenario: The turn is taken per phase

- **GIVEN** a restack whose resolver is working and another unit of the same repository that adds a worktree
- **WHEN** both proceed
- **THEN** the worktree add does not wait for the resolver

### Requirement: A restack changes no count of units

A restack SHALL NOT change which units are in progress, blocked or queued. The unit keeps its stored state and cause while it waits for the
lane and while it is moved. Waiting for a restack SHALL NOT make a unit blocked, and a unit that is blocked SHALL NOT be restacked by the
scan. The wait reason of a unit SHALL be the one it has by the existing rules, and a unit waiting for the lane SHALL NOT be given `slot` or
`queue_full` for it. The count of units in progress, the blocked units listed by the queue-full report, and the room the limit leaves SHALL be
what they were without the lane.

#### Scenario: A restack and the queue-full report

- **GIVEN** the limit on units in progress is reached, one started unit is blocked and one is being restacked
- **WHEN** the queue-full report is built
- **THEN** it counts the unit being restacked as in progress, and lists the blocked one as not counted, as it would without the lane

#### Scenario: A freshly unblocked unit owed a restack

- **GIVEN** a unit that was blocked and no longer is, waiting for room under the limit, whose base moved
- **WHEN** the scan runs
- **THEN** it is restacked while it waits for room, and starts when room opens

#### Scenario: A unit waiting for the lane is not blocked

- **GIVEN** an in-review unit queued for a restack
- **WHEN** the count of blocked units is worked out
- **THEN** it is not among them

### Requirement: The status shows restacks as their own line

While the lane has work, or a unit is owed a restack, the status SHALL show the unit as restacking onto its base and SHALL print
`restacks: N running, M waiting`. A restack waiting for a usage pause SHALL be listed with the pause as the reason. The line SHALL be
omitted when nothing runs and nothing waits. A restack SHALL NOT appear in the slot gauges or the `sample` row as a build: the free workers
and the cap SHALL be the build workers', and the lane's two counts SHALL be reported as their own gauges with no unit or change attribute.

#### Scenario: Restacks running and waiting

- **GIVEN** two restacks running and three waiting
- **WHEN** the status is read
- **THEN** it prints `restacks: 2 running, 3 waiting`, and each unit reads restacking onto its base

#### Scenario: Nothing to restack

- **WHEN** no restack runs or waits
- **THEN** the status prints no restacks line

#### Scenario: The sample row

- **GIVEN** a restack running and one build running with a cap of four
- **WHEN** a pass samples its slots
- **THEN** the free workers is three and the row has no field for the lane

#### Scenario: The status of a stopped tick

- **GIVEN** a lane record whose process has gone
- **WHEN** the status is read
- **THEN** the record is ignored and the units are shown by their stored state
