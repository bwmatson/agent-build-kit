# Spec Delta

## Purpose

Replaces the bound on open pull requests with a bound on units in progress, and
states which units count and what the bound does and does not stop.

## REMOVED Requirements

### Requirement: A workspace bounds how many pull requests may be open

**Reason**: Replaced by the bound on units in progress, which also counts
started work that has no pull request.

**Migration**: `limits.max_open_prs` is removed; set
`limits.max_units_in_progress` instead. No installation sets the old key.

### Requirement: At the ceiling, no new unit starts

**Reason**: Replaced by "At the limit, no new unit starts", which counts units
in progress rather than pull requests.

**Migration**: None needed.

### Requirement: Work on open pull requests continues at the ceiling

**Reason**: Replaced by "Work already in progress continues at the limit",
which covers started work with and without a pull request.

**Migration**: None needed.

### Requirement: Holding for a full queue is reported as such

**Reason**: Replaced by the requirement of the same intent below, reporting
units in progress.

**Migration**: None needed.

### Requirement: Free slots go to existing work first

**Reason**: Replaced by "Free slots go to existing work first, within the
limit", which no longer holds a resuming unit back: under a limit on units in
progress a resuming unit is already counted.

**Migration**: None needed.

## ADDED Requirements

### Requirement: Free slots go to existing work first, within the limit

Among the units that may start, the pipeline SHALL start those with an open pull
request before those resuming a build that was paused or held before a pull request
was opened, and those before units that have never run. Within each of the three,
units SHALL start in the order they were planned. This ordering SHALL apply only to
units the other rules allow to start: it SHALL NOT start a unit that is waiting on a
dependency or past the depth cap, and SHALL NOT start a unit that has never run
while the limit on units in progress is reached.

#### Scenario: A rework and a new unit compete for one slot

- **WHEN** one slot is free, and a unit with an open pull request that needs a
  rework and a unit that has never run are both ready
- **THEN** the unit with the open pull request starts, whichever was planned first

#### Scenario: A paused build and a new unit compete for one slot

- **WHEN** one slot is free, and a unit paused part-way through its build and a
  unit that has never run are both ready
- **THEN** the paused unit resumes first

#### Scenario: Only new units are ready

- **WHEN** every ready unit has never run
- **THEN** they start in the order they were planned, as before

#### Scenario: A resuming unit at the limit

- **WHEN** the limit on units in progress is reached and a unit with no pull
  request is resuming a paused build
- **THEN** it resumes, because it is already in progress

### Requirement: A workspace bounds how many units are in progress

The workspace SHALL configure the greatest number of units in progress at
once, defaulting to 5, counted across every repository. A unit SHALL be in
progress from the moment it first starts until it merges, is closed or is
satisfied, whatever state it is in meanwhile — running, in review, being
reworked, paused or held part-way, or failed — and whether or not it has a pull
request. A unit that has never started, including one waiting on a dependency,
SHALL NOT count.

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

### Requirement: At the limit, no new unit starts

While the number of units in progress is at or above the limit, the pipeline
SHALL NOT start a unit that has never started. Units waiting to start SHALL stay
as they are, to be started when the count falls.

#### Scenario: The limit is reached

- **WHEN** five units are in progress under the default limit and a unit that
  has never started is otherwise ready
- **THEN** it does not start, and remains planned

#### Scenario: A unit finishes

- **WHEN** a unit in progress merges and the count falls below the limit
- **THEN** a waiting unit may start under the other rules

### Requirement: Work already in progress continues at the limit

The limit SHALL NOT stop any unit that is already in progress. A rework, a
resume, a restack, a review round, a push and opening a pull request SHALL all
proceed at or over the limit, so work that is finished is never kept from its
pull request.

#### Scenario: Finished work at the limit

- **WHEN** a unit completes its review loop while the count is at the limit
- **THEN** its branch is pushed and its pull request opened

#### Scenario: A rework at the limit

- **WHEN** a unit in review is sent back for rework while the count is at the
  limit
- **THEN** the rework runs

### Requirement: Holding at the limit is reported as such

When new work is held because the limit is reached, the tick's log and the
pipeline's status SHALL say so, giving the count, the limit, and the units
holding the places by state, rather than reporting that nothing is ready.

#### Scenario: A failed unit holding a place

- **WHEN** nothing new starts because the limit is reached and one of the units
  in progress has failed
- **THEN** the report lists that unit as failed among those holding the places
