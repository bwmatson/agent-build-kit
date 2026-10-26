## ADDED Requirements

### Requirement: A running pass does everything a tick does before it starts builds

On every refresh, a running pass SHALL perform the same sequence a tick performs before it
starts builds: refresh from the code host, convert and plan new or changed changes, link
dependencies, verify and archive changes whose units have all merged, reclaim units no run
holds, and ask the usage guard, then start what fits in the free slots. The tick and the
pass SHALL use the same sequence. A step SHALL be safe to repeat, SHALL NOT alter the state,
branch or pull request of a unit being built, and a failure in one SHALL be logged without
ending the pass or skipping the others.

#### Scenario: A change written while a unit builds

- **GIVEN** a pass with a free slot and one unit building
- **WHEN** a new change is committed and the pass next refreshes
- **THEN** its units are in the store and the graph page
- **AND** a ready one starts in the free slot in the same round

#### Scenario: A change whose units have all merged

- **GIVEN** a change whose units have all merged while other units build
- **WHEN** the pass next refreshes
- **THEN** the change is verified and archived without waiting for the pass to end

#### Scenario: A killed run

- **GIVEN** a unit marked running whose run was killed, with no thread to resume
- **WHEN** the pass next refreshes
- **THEN** it is returned to planned and may start

#### Scenario: The usage window fills during a pass

- **WHEN** a round finds the guard refusing
- **THEN** it records the pause and starts nothing, and the builds in flight continue

#### Scenario: A comment resumes a unit while a pass runs

- **GIVEN** a unit in review and a pass with one other unit building
- **WHEN** a reviewer's comment resumes the unit's thread
- **THEN** the pass starts its rework in the same or the next round
- **AND** the unit never holds a slot without a run on it

#### Scenario: Nothing new

- **WHEN** a round finds nothing changed
- **THEN** no planning call is made and no unit's state changes

### Requirement: Verification does not run on a stack in use, and reclaim spares what the pass holds

A round SHALL run verification only when the live-stack lock is free, leaving the change for
the next round otherwise, and SHALL NOT reclaim a unit that a build in the pass holds or has
just been handed.

#### Scenario: A unit's live-stack run is in progress

- **GIVEN** a unit running its live-stack tests and a change ready to verify
- **WHEN** a round runs
- **THEN** verification is skipped and logged, and happens in a later round

#### Scenario: A unit just handed to a worker

- **GIVEN** a unit submitted to the pool whose worker has not yet taken its branch lock
- **WHEN** a round runs
- **THEN** the unit is not reclaimed
