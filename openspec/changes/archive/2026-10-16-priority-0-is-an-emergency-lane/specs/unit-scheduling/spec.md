## MODIFIED Requirements

### Requirement: A task group may carry a priority

A task group SHALL be able to carry a priority, an integer from 0 to 5 with 0 the most urgent (the emergency lane) and 5 the least, written as a `Priority:` line. A
line inside a group SHALL set that group's priority, and a line above the first group SHALL set the default for the change's
groups, which a group's own line overrides. A group with neither SHALL have priority 3. A value that is not an integer from 0 to
5 SHALL be reported with its line number and a message that names the range 0 to 5, and the task-tag listing SHALL show a group's priority when it is not 3. A change that
has no such line SHALL be read as before.

#### Scenario: A group sets its own priority

- **GIVEN** a group with the line `Priority: 2`
- **WHEN** the change is read
- **THEN** the group's priority is 2

#### Scenario: A group may be priority 0

- **GIVEN** a group with the line `Priority: 0`
- **WHEN** the change is read
- **THEN** the group's priority is 0 and it is not read as having none

#### Scenario: A change default

- **GIVEN** a `Priority: 4` line above the first group and one group with `Priority: 2`
- **WHEN** the change is read
- **THEN** that group's priority is 2 and the others' is 4

#### Scenario: A change default of 0

- **GIVEN** a `Priority: 0` line above the first group and one group with `Priority: 2`
- **WHEN** the change is read
- **THEN** that group's priority is 2 and the others' is 0

#### Scenario: No line

- **WHEN** a group has no priority line and the change has no default
- **THEN** its priority is 3

#### Scenario: A value outside the scale

- **GIVEN** a `Priority:` line of `6`, `-1`, `high` or `2.5`
- **WHEN** the change's tags are checked
- **THEN** the line is reported with its number and a message naming 0 to 5, and the change is not accepted

#### Scenario: A change that existed before priority 0

- **GIVEN** a `tasks.md` whose priority lines are all from 1 to 5, or absent
- **WHEN** it is read
- **THEN** every group has the priority it had before

### Requirement: A unit has the priority of its most urgent group

A unit SHALL have the most urgent (smallest) priority among the groups it builds, including groups carried from other changes, and a priority of 0 SHALL count as a priority, never as none. A
unit's effective priority SHALL be the most urgent priority among the unit and every unit that waits on it, directly or through a
chain of dependencies in any repository, not counting merged, closed or satisfied units or units the round excludes (those named
out by `--only`, held by a lease or in a backoff). A started unit SHALL keep the priority it started with when the file changes,
and a unit that has not started SHALL take the file's value when its change is next planned. A stored unit with no priority SHALL
read as 3, and a stored priority of 0 SHALL read back as 0.

#### Scenario: A unit of several groups

- **GIVEN** a unit built from a group of priority 4 and a group of priority 2
- **WHEN** its priority is read
- **THEN** it is 2

#### Scenario: A unit with a priority-0 group

- **GIVEN** a unit built from a group of priority 0 and a group of priority 3
- **WHEN** its priority is read
- **THEN** it is 0

#### Scenario: A prerequisite takes the priority of what waits on it

- **GIVEN** a priority-3 unit that a priority-1 unit waits on, directly or through a chain
- **WHEN** the effective priority is worked out
- **THEN** the prerequisite's is 1

#### Scenario: A prerequisite of a priority-0 unit

- **GIVEN** a priority-3 unit that a priority-0 unit waits on, directly or through a chain
- **WHEN** the effective priority is worked out
- **THEN** the prerequisite's is 0

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

#### Scenario: A stored priority 0 is kept

- **GIVEN** a unit of priority 0 written to the store
- **WHEN** the store is read again
- **THEN** its priority is 0, not the default 3

## ADDED Requirements

### Requirement: Priority 0 starts first and bypasses no limit

Priority 0 SHALL be the most urgent value. A unit of effective priority 0 SHALL start before a ready unit of effective priority 1 or less urgent in the
same class, with ties and classes ordered as for any other value. It SHALL NOT start a unit that is not ready, SHALL NOT stop a running unit, and SHALL
NOT bypass or raise the limit on units in progress, the cap on units running at once, a project's room or any other limit. `abk status`, `abk tags` and the graph page
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

- **GIVEN** the limit on units in progress is reached
- **WHEN** a ready unit of priority 0 is considered
- **THEN** it does not start, and it starts first when a place frees

#### Scenario: The display shows priority 0

- **GIVEN** a unit of priority 0 in the store, and a group of priority 0 in a change
- **WHEN** `abk status`, `abk tags` and the graph page are shown
- **THEN** each says `priority 0` for it
