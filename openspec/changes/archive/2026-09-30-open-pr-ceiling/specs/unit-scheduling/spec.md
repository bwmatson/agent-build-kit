# Spec Delta

## Purpose

Defines the bound on how many pull requests the pipeline may have open at once, what
that bound does and does not stop, and which unit a free slot goes to.

## ADDED Requirements

### Requirement: A workspace bounds how many pull requests may be open

The workspace SHALL configure the greatest number of pull requests the pipeline may
have open and unmerged at once, defaulting to 5, counted across every repository
rather than per repository. The count SHALL include every pull request the pipeline
has open, whatever state its unit is in, so that the configured number means the
number a person sees.

#### Scenario: The default

- **WHEN** a workspace configures no ceiling
- **THEN** at most 5 open pull requests are the trigger for holding new work

#### Scenario: Counted across repositories

- **WHEN** open pull requests are spread across several repositories
- **THEN** they count together against one ceiling

#### Scenario: A pull request that is not awaiting review

- **WHEN** a pull request is open while its unit is being reworked
- **THEN** it still counts

### Requirement: At the ceiling, no new unit starts

While the number of open pull requests is at or above the ceiling, the pipeline
SHALL NOT start a unit that has no pull request yet. Units already waiting SHALL
stay as they are, to be started when the count falls.

#### Scenario: The queue is full

- **WHEN** the ceiling is reached and a unit is otherwise ready
- **THEN** it is not started, and it remains waiting rather than failing or being
  held

#### Scenario: The queue drains

- **WHEN** a pull request merges and the count falls below the ceiling
- **THEN** waiting units become startable again under the existing rules

### Requirement: Work on open pull requests continues at the ceiling

The ceiling SHALL NOT stop anything that does not add a pull request. A unit whose
work is built and approved SHALL open or update its pull request even at the
ceiling, and a rework, a restack, a review round and a push SHALL all proceed — so
the count may briefly exceed the ceiling while in-flight work lands.

#### Scenario: Finished work at the ceiling

- **WHEN** a unit completes its review loop while the count is at the ceiling
- **THEN** its branch is pushed and its pull request opened, rather than the work
  being left unpushed

#### Scenario: Draining is never blocked

- **WHEN** a unit with an open pull request needs a rework, a restack or another
  review round while the count is at the ceiling
- **THEN** that work proceeds

### Requirement: Free slots go to existing work first

Among the units that may start, the pipeline SHALL start those with an open pull
request before those resuming a build that was paused or held before a pull request
was opened, and those before units that have never run. Within each of the three,
units SHALL start in the order they were planned. This ordering SHALL apply only to
units the other rules allow to start: it SHALL NOT start a unit that is waiting on a
dependency, past the depth cap, or held back by the ceiling.

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

#### Scenario: A resuming unit at the ceiling

- **WHEN** the queue is at the ceiling and a unit with no pull request is resuming
- **THEN** it waits, and a unit with an open pull request that needs a rework
  starts

### Requirement: Holding for a full queue is reported as such

When new work is held because the ceiling is reached, the pipeline SHALL say so
where it reports what it is doing and where a person reads its state, naming the
count and the ceiling — rather than reporting that nothing is ready, which reads as
an idle pipeline.

#### Scenario: A tick that holds everything

- **WHEN** a pass starts nothing because the queue is full
- **THEN** its log says the queue is full and gives the count and the ceiling

#### Scenario: Deciding what to do next

- **WHEN** a person reads the pipeline's status while the queue is full
- **THEN** it says the queue is full, so that reviewing something is the evident
  next action
