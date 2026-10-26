## ADDED Requirements

### Requirement: A task group may carry a priority

A task group SHALL be able to carry a priority, an integer from 1 to 5 with 1 the most urgent, written as a `Priority:` line. A
line inside a group SHALL set that group's priority, and a line above the first group SHALL set the default for the change's
groups, which a group's own line overrides. A group with neither SHALL have priority 3. A value that is not an integer from 1 to
5 SHALL be reported with its line number, and the task-tag listing SHALL show a group's priority when it is not 3. A change that
has no such line SHALL be read as before.

#### Scenario: A group sets its own priority

- **GIVEN** a group with the line `Priority: 2`
- **WHEN** the change is read
- **THEN** the group's priority is 2

#### Scenario: A change default

- **GIVEN** a `Priority: 4` line above the first group and one group with `Priority: 2`
- **WHEN** the change is read
- **THEN** that group's priority is 2 and the others' is 4

#### Scenario: No line

- **WHEN** a group has no priority line and the change has no default
- **THEN** its priority is 3

#### Scenario: A value outside the scale

- **GIVEN** a `Priority:` line of `0`, `6`, `high` or `2.5`
- **WHEN** the change's tags are checked
- **THEN** the line is reported with its number and the change is not accepted

### Requirement: A unit has the priority of its most urgent group

A unit SHALL have the most urgent (smallest) priority among the groups it builds, including groups carried from other changes. A
unit's effective priority SHALL be the most urgent priority among the unit and every unit that waits on it, directly or through a
chain of dependencies in any repository, not counting merged, closed or satisfied units or units the round excludes (those named
out by `--only`, held by a lease or in a backoff). A started unit SHALL keep the priority it started with when the file changes,
and a unit that has not started SHALL take the file's value when its change is next planned. A stored unit with no priority SHALL
read as 3.

#### Scenario: A unit of several groups

- **GIVEN** a unit built from a group of priority 4 and a group of priority 2
- **WHEN** its priority is read
- **THEN** it is 2

#### Scenario: A prerequisite takes the priority of what waits on it

- **GIVEN** a priority-3 unit that a priority-1 unit waits on, directly or through a chain
- **WHEN** the effective priority is worked out
- **THEN** the prerequisite's is 1

#### Scenario: Waiting units that are less urgent

- **GIVEN** a priority-3 unit that only priority-5 units wait on
- **WHEN** the effective priority is worked out
- **THEN** it is 3

#### Scenario: A waiter in another repository

- **GIVEN** a unit that a more urgent unit in another repository waits on
- **WHEN** the effective priority is worked out
- **THEN** it takes the waiter's priority, as a waiter in its own repository would give it

#### Scenario: A satisfied unit in the chain

- **GIVEN** a priority-1 unit that waits on a ready prerequisite through a unit that was satisfied
- **WHEN** the effective priority is worked out
- **THEN** the prerequisite's is 1

#### Scenario: A unit left out of the round gives no priority

- **GIVEN** a priority-1 unit that waits on a ready prerequisite and is left out of the round by a lease, a backoff or `--only`
- **WHEN** the effective priority is worked out
- **THEN** the prerequisite does not take priority 1

#### Scenario: A started unit keeps its priority

- **GIVEN** a unit that has started, and its group's priority line is then edited
- **WHEN** the change is next planned
- **THEN** the unit keeps the priority it had, and a unit of the same change that has not started takes the new one

#### Scenario: A record from before priorities

- **WHEN** a stored unit has no priority
- **THEN** it reads as 3

### Requirement: Priority orders ready units within their class

Within each of the classes of units that may start (those with an open pull request, those resuming a build, and those that have
never run), units SHALL start in order of effective priority, the most urgent first, and units of equal effective priority SHALL
start in the order the other ordering rules give. Priority SHALL NOT start a unit that is not ready, SHALL NOT move a unit ahead of
a unit of an earlier class, SHALL NOT stop or pause a running unit, and SHALL NOT raise the limit on units in progress or the cap
on units running at once. The status SHALL show the priority of units that are not 3, the order of the ready queue and why each
unit is where it is.

#### Scenario: A more urgent unit goes first

- **GIVEN** one place is free and two ready units that have never run, the later planned of priority 1 and the other of priority 3
- **WHEN** units are chosen
- **THEN** the priority-1 unit starts first

#### Scenario: A prerequisite of an urgent unit goes ahead of an older one

- **GIVEN** a ready priority-3 unit that a priority-1 unit waits on, and an older ready priority-3 unit that nothing waits on
- **WHEN** one place is free
- **THEN** the prerequisite starts first

#### Scenario: A prerequisite of only nice-to-have units does not take a normal unit's place

- **GIVEN** a ready priority-3 unit that only newer priority-5 units wait on, and an older ready priority-3 unit that nothing waits on
- **WHEN** one place is free
- **THEN** the older unit starts first

#### Scenario: Equal priority falls to the other rules

- **GIVEN** two ready units that have never run, with the same effective priority
- **WHEN** units are chosen
- **THEN** they start in the order the other ordering rules give, and in the order they were planned where those do not decide

#### Scenario: Work in progress is not displaced

- **GIVEN** a ready priority-1 unit that has never run, and a unit with an open pull request or a paused build, of priority 5
- **WHEN** one place is free
- **THEN** the unit with the pull request, then the paused build, starts first

#### Scenario: A running unit keeps running

- **GIVEN** the cap on units running at once is reached and a ready priority-1 unit
- **WHEN** units are chosen
- **THEN** no running unit is stopped and the priority-1 unit does not start

#### Scenario: The limit is not exceeded

- **GIVEN** the limit on units in progress is reached and a ready priority-1 unit that has never run
- **WHEN** units are chosen
- **THEN** it does not start, and starts when a place is free

#### Scenario: A unit that is not ready

- **GIVEN** a priority-1 unit waiting on a dependency, and a ready priority-5 unit
- **WHEN** one place is free
- **THEN** the priority-5 unit starts

#### Scenario: The status shows the order

- **GIVEN** a ready unit of priority 1 and ready units of priority 3
- **WHEN** the status is read
- **THEN** the priority-1 unit is marked, and the ready queue is listed in start order with the reason each is where it is
