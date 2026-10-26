## MODIFIED Requirements

### Requirement: A workspace bounds how many units are in progress

The workspace SHALL configure the greatest number of units in progress at
once, defaulting to 5, counted across every repository. A unit SHALL be in
progress from the moment it first starts until it merges, is closed or is
satisfied, whatever state it is in meanwhile — running, in review, being
reworked, paused or held part-way, or failed — and whether or not it has a pull
request. A unit that has never started, including one waiting on a dependency,
SHALL NOT count. A started unit that is blocked (a planned unit waiting on another unit) SHALL NOT
count while it is blocked, and counts again from the moment it is not. A failed unit that waits on
another unit (the units it waits on are those that stop a unit starting: a dependency not yet merged or
reviewed, or a predecessor being reworked, failed or held) SHALL NOT count while it waits, SHALL count again from the moment
the wait ends, and SHALL stay failed throughout: it is never requeued by the pipeline.

#### Scenario: Started work without a pull request

- **WHEN** a unit is paused part-way through its build and has no pull request
- **THEN** it counts as in progress

#### Scenario: A failed unit

- **WHEN** a unit has failed and waits on no other unit (a failed unit that does wait is the next scenario)
- **THEN** it counts as in progress until it is requeued and finishes, or is
  closed

#### Scenario: A failed unit waiting on a prerequisite

- **WHEN** a unit has failed and waits on a prerequisite that has not merged, or on a predecessor that is being reworked, failed or held
- **THEN** it does not count, it is still failed, and it counts again, still failed and not requeued, when the wait ends

#### Scenario: Blocked new work

- **WHEN** a unit has never started and is waiting on a dependency
- **THEN** it does not count

#### Scenario: A blocked unit that has work

- **WHEN** a unit has a branch and a run log, is planned, and is waiting on a prerequisite that has not merged
- **THEN** it does not count, and counts again when the prerequisite has merged

### Requirement: Holding at the limit is reported as such

When new work is held because the limit is reached, the tick's log and the
pipeline's status SHALL say so, giving the count, the limit, and the units
holding the places by state, rather than reporting that nothing is ready, and SHALL say how many blocked units are not counted and
what each waits on. A failed unit that waits on another unit SHALL NOT be listed among the units holding the places, and the report SHALL say how many
of them are not counted.

#### Scenario: A failed unit holding a place

- **WHEN** nothing new starts because the limit is reached and one of the units
  in progress has failed
- **THEN** the report lists that unit as failed among those holding the places

#### Scenario: Blocked units are listed

- **WHEN** the queue is full and two started units are blocked
- **THEN** the report says two blocked units are not counted and lists each with what it waits on

#### Scenario: A failed unit that waits is not listed as holding a place

- **WHEN** the queue is full and one failed unit waits on a prerequisite
- **THEN** the report does not count it or list it among the units holding the places, and says one failed unit waiting is not counted

## ADDED Requirements

### Requirement: A failed unit that waits is shown as waiting

The status and the graph SHALL show a failed unit that waits on another unit as failed and waiting, naming the units it waits on, and SHALL
NOT change its state, its pull request or its labels there. Its wait ending SHALL NOT start it, requeue it or give it a place ahead of any other unit.

#### Scenario: The status

- **WHEN** a failed unit waits on a prerequisite and the status is read
- **THEN** the status shows it as failed, waiting on that prerequisite, in addition to its failed line

#### Scenario: The graph

- **WHEN** the graph is drawn with a failed unit that waits on a prerequisite
- **THEN** the unit is drawn as failed with the label `failed, waiting on` and the prerequisite, and a failed unit that waits on nothing is drawn as failed

#### Scenario: The wait ends at the limit

- **WHEN** a failed unit's wait ends while the count of the other units is at the limit
- **THEN** the unit counts again and starts nothing, no unit already in progress is stopped, and no new unit starts until the count falls below the limit
