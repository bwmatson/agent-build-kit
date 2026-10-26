## MODIFIED Requirements

### Requirement: A workspace bounds how many units are in progress

The workspace SHALL configure the greatest number of units in progress at
once, defaulting to 5, counted across every repository. A unit SHALL be in
progress from the moment it first starts until it merges, is closed or is
satisfied, whatever state it is in meanwhile — running, in review, being
reworked, paused or held part-way, or failed — and whether or not it has a pull
request. A unit that has never started, including one waiting on a dependency,
SHALL NOT count. A started unit that is blocked (a planned unit waiting on another unit) SHALL NOT
count while it is blocked, and counts again from the moment it is not.

#### Scenario: Started work without a pull request

- **WHEN** a unit is paused part-way through its build and has no pull request
- **THEN** it counts as in progress

#### Scenario: A failed unit

- **WHEN** a unit has failed
- **THEN** it counts as in progress until it is requeued and finishes, or is
  closed

#### Scenario: Blocked new work

- **WHEN** a unit has never started and is waiting on a dependency
- **THEN** it does not count

#### Scenario: A blocked unit that has work

- **WHEN** a unit has a branch and a run log, is planned, and is waiting on a prerequisite that has not merged
- **THEN** it does not count, and counts again when the prerequisite has merged

### Requirement: Work already in progress continues at the limit

The limit SHALL NOT stop any unit that is already in progress. A rework, a
resume, a restack, a review round, a push and opening a pull request SHALL all
proceed at or over the limit, so work that is finished is never kept from its
pull request. A planned unit that was blocked and no longer is the exception: it SHALL start only while the number of
other units in progress is below the limit, and until then it stays planned.

#### Scenario: Finished work at the limit

- **WHEN** a unit completes its review loop while the count is at the limit
- **THEN** its branch is pushed and its pull request opened

#### Scenario: A rework at the limit

- **WHEN** a unit in review is sent back for rework while the count is at the
  limit
- **THEN** the rework runs

#### Scenario: A freshly unblocked unit at the limit

- **WHEN** a unit that was blocked becomes unblocked while the number of other units in progress is at the limit
- **THEN** it stays planned, and starts when a unit finishes

#### Scenario: A unit paused for usage at the limit

- **WHEN** a planned unit was paused by a usage pause, not blocked, while the count is at the limit
- **THEN** it resumes, as before

### Requirement: Holding at the limit is reported as such

When new work is held because the limit is reached, the tick's log and the
pipeline's status SHALL say so, giving the count, the limit, and the units
holding the places by state, rather than reporting that nothing is ready, and SHALL say how many blocked units are not counted and
what each waits on.

#### Scenario: A failed unit holding a place

- **WHEN** nothing new starts because the limit is reached and one of the units
  in progress has failed
- **THEN** the report lists that unit as failed among those holding the places

#### Scenario: Blocked units are listed

- **WHEN** the queue is full and two started units are blocked
- **THEN** the report says two blocked units are not counted and lists each with what it waits on

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
progress is reached. Before those classes, a ready unit that is a prerequisite of a blocked unit that would
otherwise count SHALL start first into that unit's slot, one slot for each blocked unit and one unit for each
slot, several of them in order of effective priority, then effective age; this SHALL NOT exceed the limit or the cap on units running at once.

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
- **THEN** the blocked unit does not count, the prerequisite starts into its place ahead of every other unit, and the count stays at or below the limit

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

## ADDED Requirements

### Requirement: A blocked unit does not hold a place

A planned unit SHALL be blocked when a unit it depends on or must follow has not merged or been satisfied, when its predecessor is being
reworked, failed or held, or when its cause is `gated` or `upstream_went_back`. A backoff for the host being unavailable, a lease,
a tick limited to named units and a usage pause SHALL NOT make a unit blocked. A blocked unit SHALL be shown as blocked by the status and the graph, whatever its stored state.

#### Scenario: Waiting on a prerequisite

- **GIVEN** a planned unit with work whose prerequisite is in review
- **WHEN** the status is read
- **THEN** it is shown as blocked and is not counted

#### Scenario: A usage pause is not a block

- **GIVEN** a planned unit paused by a usage pause with no unmet prerequisite
- **WHEN** the count is worked out
- **THEN** it counts

#### Scenario: Kept from going back by its predecessor

- **GIVEN** a unit in review set back to planned because its predecessor is changing
- **WHEN** the count is worked out
- **THEN** it does not count until the predecessor is back in review
