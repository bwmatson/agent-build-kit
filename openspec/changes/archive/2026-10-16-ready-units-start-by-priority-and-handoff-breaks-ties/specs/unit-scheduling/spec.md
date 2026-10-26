## MODIFIED Requirements

### Requirement: Free slots go to existing work first, within the limit

Among the units that may start, the pipeline SHALL start those with an open pull
request before those resuming a build that was paused or held before a pull request
was opened, and those before units that have never run. Within the first two,
units SHALL start in the order they were planned. Within the units that have never
run, units SHALL start in order of their effective priority (the most urgent priority
among the unit and every unit that waits on it) and, between units of equal effective
priority, of their effective age: the earliest planned position
among the unit and every unit that waits on it, directly or through a chain of
dependencies in any repository, not counting merged, closed or satisfied units or units the round excludes (those named
out by `--only`, held by a lease or in a backoff), with a tie going to the
unit's own planned position. The order SHALL NOT depend on the depth of a stack or on
how many units wait. This ordering SHALL apply only to units the other rules allow to
start: it SHALL NOT start a unit that is waiting on a dependency or past the depth
cap, and SHALL NOT start a unit that has never run while the limit on units in
progress is reached. A ready unit that has never run and is a prerequisite of a blocked unit that would
otherwise count is a handoff unit: it takes that unit's slot, one slot for each blocked unit and one unit for each
slot, several of them in order of effective priority, then effective age. A handoff unit SHALL NOT start ahead of a more urgent unit that has never run: among
units that have never run the order is effective priority, then handoff units before the others of equal priority, then effective age, then planned position. Open pull requests
and resumed builds still come first. A handoff unit SHALL start whenever no more urgent unit that has never run can, so the slot a blocked unit frees is not left empty. None of this SHALL exceed the limit or the cap on units running at once.

#### Scenario: A rework and a new unit compete for one slot

- **WHEN** one slot is free, and a unit with an open pull request that needs a
  rework and a unit that has never run are both ready
- **THEN** the unit with the open pull request starts, whichever was planned first

#### Scenario: A paused build and a new unit compete for one slot

- **WHEN** one slot is free, and a unit paused part-way through its build and a
  unit that has never run are both ready
- **THEN** the paused unit resumes first

#### Scenario: Only new units are ready

- **WHEN** every ready unit has never run and none has any unit waiting on it
- **THEN** they start in the order they were planned, as before

#### Scenario: A resuming unit at the limit

- **WHEN** the limit on units in progress is reached and a unit with no pull
  request is resuming a paused build
- **THEN** it resumes, because it is already in progress

#### Scenario: A prerequisite of an old unit goes ahead of newer work

- **GIVEN** a ready unit with an old unit waiting on it, and a newer ready unit that nothing waits on
- **WHEN** one place is free
- **THEN** the prerequisite starts first, although it was planned after the newer unit

#### Scenario: A prerequisite of a priority-1 unit goes ahead of an older priority-3 one

- **GIVEN** a ready priority-3 unit that a priority-1 unit waits on, and an older ready priority-3 unit that nothing waits on
- **WHEN** one place is free
- **THEN** the prerequisite starts first, whatever the ages

#### Scenario: A unit that gates several waiting units goes ahead of standalone ones

- **GIVEN** a ready unit planned late, with two older units waiting on it, and several ready units that nothing waits on and that were planned after the waiting ones but before it
- **WHEN** places free one at a time
- **THEN** the unit that gates the waiting ones starts first, and the standalone units follow in the order they were planned

#### Scenario: A prerequisite of only newer units does not take an older unit's place

- **GIVEN** a ready unit with only a newer unit waiting on it, and an older ready unit that nothing waits on
- **WHEN** one place is free
- **THEN** the older unit starts first

#### Scenario: A chain

- **GIVEN** a ready unit, a unit waiting on it, and an older unit waiting on that one
- **WHEN** the order is worked out
- **THEN** the ready unit takes the age of the oldest in the chain

#### Scenario: Depth and number of waiters do not matter

- **GIVEN** one ready unit with a long chain of newer units waiting on it, and another with one old unit waiting on it
- **WHEN** the order is worked out
- **THEN** the second starts first, because the unit waiting on it is older

#### Scenario: A unit waiting on two prerequisites

- **GIVEN** an old unit waiting on two ready prerequisites
- **WHEN** the order is worked out
- **THEN** both take its age

#### Scenario: A satisfied unit in the chain

- **GIVEN** an old unit that waits on a ready prerequisite through a unit that was satisfied
- **WHEN** the order is worked out
- **THEN** the prerequisite takes the old unit's age

#### Scenario: The limit is not exceeded

- **GIVEN** the limit on units in progress is reached and a ready prerequisite of an old unit
- **WHEN** units are chosen
- **THEN** it does not start, and starts when a place is free

#### Scenario: Work in progress is not displaced

- **GIVEN** a ready prerequisite of an old unit and a unit with an open pull request that needs a rework
- **WHEN** one place is free
- **THEN** the unit with the open pull request starts first

#### Scenario: Only the named units

- **GIVEN** a tick limited to named units and a ready prerequisite that is not named
- **WHEN** units are chosen
- **THEN** it is not started

#### Scenario: A unit left out by a lease or a backoff gives no age

- **GIVEN** an old unit that waits on a ready prerequisite and is itself left out of the round by a lease or a backoff, and a newer ready unit that nothing waits on
- **WHEN** one place is free
- **THEN** the newer unit starts first, because the old unit is not counted as waiting this round

#### Scenario: A waiter in another repo

- **GIVEN** a ready unit with an old unit in another repository waiting on it
- **WHEN** one place is free
- **THEN** the unit takes the old unit's age, as a waiter in its own repository would give it

#### Scenario: A prerequisite takes the slot of the unit it blocks

- **GIVEN** the limit is reached, one of the units in progress is blocked and has work, and its prerequisite is ready and has never run
- **WHEN** units are chosen
- **THEN** the blocked unit does not count, the prerequisite starts into its place ahead of every other unit that has never run and has the same effective priority, and the count stays at or below the limit

#### Scenario: Several handoffs are ordered by priority

- **GIVEN** two blocked units that have work, each with its own ready prerequisite, one waited on by a priority-1 unit and the other by an older priority-3 unit
- **WHEN** units are chosen and only one place can be given
- **THEN** the prerequisite of the priority-1 unit takes it

#### Scenario: Two blocked units and one prerequisite

- **GIVEN** the limit is reached by five units, two of them blocked on the same ready prerequisite
- **WHEN** units are chosen
- **THEN** the prerequisite takes one place, and the other place goes to the next unit by the usual order

#### Scenario: A prerequisite of a unit that never started

- **GIVEN** a ready prerequisite whose only waiter has never started
- **WHEN** units are chosen at the limit
- **THEN** it gets no place of its own, and follows the effective age order

#### Scenario: The handoff stays within the other rules

- **GIVEN** a prerequisite that is outside the units named by `--only`, held by a lease or in a backoff, or the cap on units running at once is reached
- **WHEN** units are chosen
- **THEN** it is not started

#### Scenario: A more urgent new unit starts before a handoff unit

- **GIVEN** a blocked unit with work that frees a place, its ready priority-2 prerequisite that has never run, and two ready priority-1 units that have never run and that nothing waits on
- **WHEN** units are chosen and there is room for all three
- **THEN** the two priority-1 units are offered before the priority-2 prerequisite, and the prerequisite starts after them

#### Scenario: Handoff units go first among equal priorities, then by age

- **GIVEN** two ready priority-3 handoff units, an older and a newer, and an older ready priority-3 unit that is not a handoff unit
- **WHEN** units are chosen
- **THEN** the older handoff unit starts first, the newer handoff unit second, and the unit that is not a handoff unit last, although it is the oldest

#### Scenario: Existing work still goes before a more urgent new unit

- **GIVEN** a paused priority-3 unit with work and a ready priority-1 unit that has never run, whichever is a handoff unit
- **WHEN** one place is free
- **THEN** the paused unit resumes first

#### Scenario: A less urgent handoff unit still gets the freed place

- **GIVEN** the limit is reached, one unit in progress is blocked and has work, and its only ready prerequisite is a priority-3 unit that has never run, with no more urgent ready unit
- **WHEN** units are chosen
- **THEN** the prerequisite starts into the blocked unit's place, and the count stays at or below the limit

#### Scenario: A more urgent unit that the limits skip leaves the place to the handoff unit

- **GIVEN** a freed place, a ready priority-1 unit of a project that is full, and a ready priority-3 handoff unit of a project with room
- **WHEN** units are chosen
- **THEN** the priority-1 unit is skipped and the handoff unit starts

## ADDED Requirements

### Requirement: The ready queue marks a handoff unit

`abk status` SHALL mark with `(handoff)`, after its reason, each unit in the ready queue that is a handoff unit (a ready unit that has never run and
takes the place a blocked unit frees), so the start order can be explained when a handoff unit stands among units of its own priority. The marker
SHALL NOT appear on a unit that is not a handoff unit, and SHALL NOT change the order or the reason shown.

#### Scenario: Status shows a handoff unit

- **GIVEN** a blocked unit with work, its ready priority-2 prerequisite that has never run, and a ready priority-1 unit that has never run
- **WHEN** the status is read
- **THEN** the ready queue lists the priority-1 unit first, without a marker, and the prerequisite second, as `priority 2 (handoff)`

#### Scenario: No handoff unit

- **GIVEN** no blocked unit that has work and would otherwise count
- **WHEN** the status is read
- **THEN** no line of the ready queue carries the marker
