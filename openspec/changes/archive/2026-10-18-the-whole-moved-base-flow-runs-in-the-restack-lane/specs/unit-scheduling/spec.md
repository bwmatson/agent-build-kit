## MODIFIED Requirements

### Requirement: A restack takes no build slot and no start admission

Moving a unit onto a changed base, and every step of a run whose only reason to run is that its base moved (a moved-base run), SHALL run
in a lane of its own, outside the workers that build units. It SHALL NOT be refused or delayed by a lack of free build workers, SHALL NOT
be held back by the builds running, SHALL NOT stop or delay a build already running, and SHALL NOT be admitted by the limit on units in
progress: the unit it moves is already in progress or already not, and moving it is not a start. Its only admission SHALL be the lane's own
cap and the usage guard. It SHALL count toward the slot occupancy of its project (the requirement on occupancy below), so that no build
starts while the occupancy is at or above `max_concurrent_stacks`, but it SHALL NOT wait for room under that cap. The port of a conflict the resolver could not settle, a rework of the conflict
kind, tier 1 on the result, the review of a resolved move, the check against the base and the push of a rewritten head SHALL be steps of
that run and SHALL run in the lane. Rework that is not about the move (a reviewer's comment, failing checks, tier 2 feedback) and the
build of a new unit SHALL run in a build worker as before.

#### Scenario: Every build slot is busy

- **GIVEN** every build slot is taken by a build and a parent merges, so a child's branch must move onto its new base
- **WHEN** the merge is seen
- **THEN** the child's restack runs at once, and no build is stopped, delayed or given up for it

#### Scenario: A restack running does not reduce the free workers

- **GIVEN** a cap of four, two builds running and a restack running in the lane
- **WHEN** the pass samples its slots
- **THEN** the restack was not refused or delayed for want of a worker, it counts toward the occupancy (three), so the sample's free workers is one and not two, and a unit that is ready starts in the one free slot

#### Scenario: A unit at the limit on units in progress

- **GIVEN** the number of units in progress is at the limit and a unit already in progress has a moved base
- **WHEN** the unit is restacked
- **THEN** it is moved, and no admission is asked of the limit

#### Scenario: A port in the lane

- **GIVEN** every build slot is taken and a unit's resolved move lost some of its own tests, so it is planned for a restack conflict
- **WHEN** the unit is found
- **THEN** its port, tier 1, review and push run in the lane, and no build worker is waited for

#### Scenario: A reviewer's comment during a moved-base run

- **GIVEN** a moved-base run in the lane whose review asks for changes that are not about the move
- **WHEN** the run reaches the rework
- **THEN** the lane does not run it, and the unit waits for a build worker with the rework as its reason

### Requirement: A restack starts when it is seen

A restack SHALL start when the pipeline sees that a unit's base moved, and SHALL NOT wait for the next tick or for a build slot. The base
SHALL be seen by the merge, release and depth handlers when the poller reports the event, by a scan after every poll, every finished
build, every finished restack and every usage pause, and by the end of a run that left its unit planned for a moved base. The scan SHALL
find every unit owed a restack: one that is planned, running with a parked thread, or in review, whose cause is a moved base or a deferred
restack, whose branch does not hold its base, that no run holds, and that is not waiting on another unit. A unit planned for a restack conflict, and
one planned for a deferred restack whose branch already holds its base (a resolved move waiting for its review), SHALL NOT be moved again;
each is owed the moved-base run that follows the move, and the scan SHALL hand it to the lane to run. A restack that could start when a lane worker is free SHALL start before the handler that saw it returns; one that cannot SHALL
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
- **THEN** it is not restacked again, and its tier 1, review and push run in the lane

#### Scenario: A conflict the resolver could not settle

- **GIVEN** a unit left planned for a restack conflict
- **WHEN** a scan runs
- **THEN** it is not restacked again, and the lane runs its port and what follows

#### Scenario: A unit waiting on another unit

- **GIVEN** a planned unit that waits on a unit that has not merged
- **WHEN** a scan runs
- **THEN** it is not restacked, and is restacked once it is no longer waiting

#### Scenario: A unit owed a restack is not started for it

- **GIVEN** a unit owed a restack while a build slot is free
- **WHEN** the pass looks for what to start
- **THEN** the slot is not given to the unit for its move or for a run that is about the move, and it is started in a build worker only for rework of its own

## ADDED Requirements

### Requirement: A moved-base run is a run whose only reason is that the base moved

A run SHALL be a moved-base run when the unit has commits on its branch, is not held by a person, a lease or another run, is not waiting
on another unit, and has no rework input of its own, and its stored cause is a moved base, a deferred restack or a restack conflict, or it
was sent back by the host reporting its pull request as conflicting. A unit held by a run that found its base moved twice SHALL be one. A
unit has rework input of its own when it has saved feedback from a review, a failing check or a test run that is not the feedback of the
conflict, unless review has since approved the branch's head; answered feedback SHALL be cleared as the run starts, and feedback that
names the conflict SHALL NOT be rework input. A run that is not a moved-base run SHALL be a build and run in a build worker; the lane
SHALL still move such a unit as before.

#### Scenario: Each cause

- **GIVEN** units with commits whose causes are a moved base, a deferred restack, a restack conflict, and a conflict sent back
- **WHEN** each is judged
- **THEN** each is owed a moved-base run

#### Scenario: A second find of a moved base

- **GIVEN** a unit a run held planned because its base moved twice in the run
- **WHEN** it is judged
- **THEN** it is owed a moved-base run

#### Scenario: A reviewer's feedback is still to be answered

- **GIVEN** a unit with saved review feedback that no approval covers and a moved base
- **WHEN** it is judged
- **THEN** it is not owed a moved-base run, the lane moves it as before, and it waits for a build worker for its rework

#### Scenario: Answered feedback

- **GIVEN** a unit with saved review feedback whose branch head review has since approved, and a moved base
- **WHEN** its run starts
- **THEN** the feedback is cleared, the run is a moved-base run, and the rework step is not run for it

#### Scenario: A unit with no commits

- **GIVEN** a planned unit with no commits whose base changed
- **WHEN** it is judged
- **THEN** it is a build, not a moved-base run

#### Scenario: Held by a person, a lease or another run

- **GIVEN** a unit held, leased or with its branch held, whose base moved
- **WHEN** it is judged
- **THEN** it is not owed a run

### Requirement: A moved-base run holds a lane worker for its whole length

The lane SHALL run a moved-base run in one of its workers, with the unit's branch held, from the move until the unit waits for review, is
held, fails, is satisfied, is handed back, or is interrupted. The run SHALL run as a build worker's run does, in the unit's own session
where it has one, with its own run log, and SHALL end as a build worker's ends (a usage pause pauses the pass, an unreachable network
parks the unit, an error fails it). It SHALL NOT take a build worker from the pool and SHALL NOT be refused or delayed by a lack of free
build workers; it SHALL be admitted by the lane's own cap (`project_limits.max_concurrent_restacks`, for the unit's project) and the usage
guard alone, in the order the runs were seen, while it SHALL count toward slot occupancy once it runs (the requirement on occupancy below).
It SHALL NOT change the limit on units in progress, since the unit is the one already in progress. A run that was interrupted by a lost process or a usage pause SHALL be resumed by the lane and SHALL NOT be started by a build
worker.

#### Scenario: Every build worker is busy

- **GIVEN** every build worker is running and a unit owed a moved-base run
- **WHEN** the run is handed over
- **THEN** it starts in the lane at once, no build is stopped or delayed, and the run is not refused for want of a free worker

#### Scenario: Free workers fall as the run counts

- **GIVEN** a cap of four, one build running and a moved-base run in the lane, the unit stored as running
- **WHEN** the pass counts its workers and samples its slots
- **THEN** the occupancy is two, the free workers is two, and a ready unit starts in a free worker

#### Scenario: The lane's own cap

- **GIVEN** a lane of 2 and three units owed a moved-base run
- **WHEN** they are handed over
- **THEN** two runs are in the lane, the third waits in the order seen and starts when one ends

#### Scenario: The limit on units in progress

- **GIVEN** the number of units in progress is at its limit and a unit already in progress owed a moved-base run
- **WHEN** the run starts
- **THEN** it starts, and the number in progress is as it was

#### Scenario: A clean move needs no run

- **GIVEN** a unit in review whose approved head moves cleanly onto its base with an unchanged diff
- **WHEN** the lane moves it
- **THEN** tier 1 and the push of the stack move are all it does, and no run is made

#### Scenario: The move is not the end

- **GIVEN** a move that needed the resolver and changed the diff
- **WHEN** the lane has moved the unit
- **THEN** the same lane worker goes on into tier 1 and the review of the result, and does not leave the unit for a build worker

#### Scenario: A lost process

- **GIVEN** a moved-base run whose process was killed in the middle of the review, the unit stored as running with its thread there
- **WHEN** the next tick scans
- **THEN** the lane resumes it at the review, and no build worker is offered it

### Requirement: A moved-base run stops before work that is not about the move, and hands the unit back

A moved-base run SHALL consist of the move, the resolver, the port, a rework whose feedback is the conflict's, tier 1 on the result, the
review of the result, the check against the base, the comments step, the push and the pull request step. It SHALL NOT run a rework that
answers a reviewer, a comment or a failing check, SHALL NOT run a fix of failing checks, and SHALL NOT run tier 2. A unit that reaches
one of them SHALL have finished its current step, SHALL be left planned with the cause `restack_handed_back` and a note naming the step
and the reason, SHALL keep its thread positioned at that step, and SHALL be started from that step by a build worker like any rework; the
lane SHALL NOT continue it. A running pass SHALL let such a unit back in. A handed-back unit whose base moves again SHALL be judged
afresh.

#### Scenario: The review asks for changes

- **GIVEN** a moved-base run whose review of the resolved move answers with changes
- **WHEN** the thread reaches the rework
- **THEN** the lane does not run it; the unit is planned with `restack_handed_back`, the thread at the rework, and the note says the review asked for changes

#### Scenario: A check fails after the port

- **GIVEN** a moved-base run whose tier 1 fails after the port
- **WHEN** the thread would fix the checks
- **THEN** the unit is handed back with the thread at the fix of the checks

#### Scenario: A unit whose tests are end-to-end

- **GIVEN** a moved-base run of a unit whose tier is end-to-end, approved by review
- **WHEN** the thread would run tier 2
- **THEN** the unit is handed back with the thread at tier 2

#### Scenario: A build worker takes it from the step

- **GIVEN** a unit handed back at the rework
- **WHEN** a build worker takes it
- **THEN** it runs from the rework, the move is not made again, and the lane has no part in it

#### Scenario: The hand-back is not a failure

- **WHEN** a unit is handed back
- **THEN** it is not failed or held, its approval and pull request are as they were, and a running pass lets it back in

#### Scenario: A conflict rework is not handed back

- **GIVEN** a moved-base run whose rework carries the conflict's feedback
- **WHEN** the thread reaches the rework
- **THEN** the lane runs it

#### Scenario: A run that needs nothing else

- **GIVEN** a moved-base run whose move is clean and whose review approves
- **WHEN** the run reaches the push
- **THEN** it pushes and the unit waits for review, with no worker of the build pool used

### Requirement: A moved-base run counts toward slot occupancy, and no build starts at or above the cap

For each project, the slot occupancy SHALL be the number of distinct unit ids among the builds in flight, the moved-base runs currently
running in the lane (a move, or the run that follows it) and the units stored running as the counts already take them. A unit that is
more than one of these (a lane unit that is also stored running, as one left with `restack_conflict` or `restack_deferred` is) SHALL be
counted once. Work waiting in the lane behind `project_limits.max_concurrent_restacks` SHALL NOT be counted until it runs. The free
workers SHALL be `max(0, max_concurrent_stacks - occupancy)`. A moved-base run SHALL start whatever the occupancy is, so the occupancy MAY
exceed the cap, by lane work only. While the occupancy is at or above the cap, no build SHALL start: not a new start and not a resume,
which is every start that `max_concurrent_stacks` gates. The size of the pool of build workers, the lane's admission, the scan for owed runs
and the choice of what the lane runs SHALL NOT read the occupancy. The limit on units in progress SHALL be unchanged, since the unit of a
run is already counted as in progress.

#### Scenario: A run starts when every worker is busy

- **GIVEN** a cap of four and four builds running, and a base moves so a unit is owed a moved-base run
- **WHEN** the run is handed over
- **THEN** it starts at once, and the occupancy reads 5/4

#### Scenario: No new build starts while a run holds the room

- **GIVEN** a cap of four, three builds running and a moved-base run running in the lane, and a ready unit
- **WHEN** the pass looks for what to start
- **THEN** the occupancy is four, the free workers is zero, and the unit is not started, whether it is new or a resume

#### Scenario: A new build starts once the run ends and the occupancy is below the cap

- **GIVEN** a cap of four, three builds running and a moved-base run that has just ended, and a ready unit
- **WHEN** the next pass looks for what to start
- **THEN** the occupancy is three, the free workers is one, and the unit starts in it

#### Scenario: A build does not start over the cap

- **GIVEN** a cap of four, four builds running and two moved-base runs running, so the occupancy reads 6/4
- **WHEN** one build ends and the pass looks for what to start
- **THEN** the occupancy is five, the free workers is zero, and no build starts until the occupancy is below four

#### Scenario: Occupancy counts a unit once

- **GIVEN** a unit that is stored running and is also running in the lane, as one left with `restack_conflict` is, and a unit that is in flight and stored running
- **WHEN** the occupancy is counted
- **THEN** each of them counts once

#### Scenario: Work waiting in the lane is not counted until it runs

- **GIVEN** a lane of 2 with two runs running and a third unit owed one, stored running, queued behind the lane's cap
- **WHEN** the occupancy is counted
- **THEN** it holds the two running units and not the queued one, and when a run ends and the third starts it is counted

#### Scenario: The lane does not read the occupancy

- **GIVEN** an occupancy at or above the cap and units owed a moved-base run within the lane's cap
- **WHEN** the lane admits and scans
- **THEN** it admits them by its own cap and the usage guard only, and the pool of build workers keeps its size

#### Scenario: The limit on units in progress is unchanged

- **GIVEN** the number of units in progress at its limit and a unit already in progress owed a moved-base run
- **WHEN** the run starts and the occupancy is counted
- **THEN** the number in progress is as it was, and the run is counted once in the occupancy

### Requirement: The status shows the whole of a moved-base run as restacking

While a unit's moved-base run is queued or running in the lane, the status and the graph SHALL show the unit as restacking onto its base,
and `restacks: N running, M waiting` SHALL count the run as one restack, running or waiting. The unit SHALL read so for the whole of the
run and not only for the move. The slot gauges (`abk.slots.free`, `abk.slots.idle_with_ready`) and the `sample` row SHALL report the
occupancy, which counts the run: the row's running count MAY exceed its cap, and its free workers is clamped at zero. `abk status` SHALL
print a slots line of the occupancy over the cap, with the number of restacks in the lane, such as `slots: 5/4, 1 restacking`.

#### Scenario: A run in its review

- **GIVEN** a moved-base run in the lane that has reached the review of the result
- **WHEN** the status is read
- **THEN** the unit reads restacking onto its base and the restacks line counts it as running

#### Scenario: A run waiting for a lane worker

- **GIVEN** a lane of 2 with two runs and a third unit owed one
- **WHEN** the status is read
- **THEN** the line reads `restacks: 2 running, 1 waiting`

#### Scenario: A handed-back unit

- **GIVEN** a unit handed back to the build queue
- **WHEN** the status is read
- **THEN** it no longer reads as restacking, and the restacks line does not count it

#### Scenario: The sample row

- **GIVEN** a moved-base run in the lane and one build running with a cap of four
- **WHEN** a pass samples its slots
- **THEN** the free workers is two, the running count is two, and the two gauges read the same occupancy

#### Scenario: The sample row over the cap

- **GIVEN** four builds running and a moved-base run in the lane with a cap of four
- **WHEN** a pass samples its slots
- **THEN** the running count is five, the free workers is zero and not negative, and the gauge `abk.slots.free` is zero

#### Scenario: abk status shows the slots line

- **GIVEN** four builds running and one moved-base run in the lane with a cap of four
- **WHEN** the status is read
- **THEN** it prints `slots: 5/4, 1 restacking`, and with no run in the lane it prints the occupancy over the cap with no restacking count
