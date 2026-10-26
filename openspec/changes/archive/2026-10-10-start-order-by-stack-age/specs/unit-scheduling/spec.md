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
progress is reached.

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

## ADDED Requirements

### Requirement: A failed prerequisite with waiting units is named

When a failed unit has units waiting on it, the status SHALL list it with the number of units waiting and say it needs a requeue,
and the reason given when nothing could start SHALL name it.

#### Scenario: Units wait on a failed unit

- **GIVEN** a failed unit and two units waiting on it
- **WHEN** the status is read
- **THEN** it names the failed unit, says two units wait on it, and says to requeue it

#### Scenario: Nothing could start

- **GIVEN** the only unit that could unblock others is failed
- **WHEN** nothing is started
- **THEN** the reason names the failed unit and does not say only that nothing is ready
