## ADDED Requirements

### Requirement: A wait is one span carrying its reason

A stretch a unit spends not running SHALL be recorded as a single span whose `waited` field names its reason and which names no node, for every reason in the defined set, and no stretch SHALL be recorded both as a wait and as a node. A review round SHALL be recorded as a span with a cause of review, check or conflict, a conflict being the rework a restack started. A usage-paused unit SHALL display as paused without a new stored state.

#### Scenario: A wait recorded once

- **WHEN** a unit waits for a slot and later starts
- **THEN** one span carries `waited` of `slot` and the wait metric counts it once

#### Scenario: A rework from a restack

- **WHEN** a restack sends a unit back for rework
- **THEN** its round's span has the cause conflict

#### Scenario: A paused unit

- **WHEN** a unit is parked on a usage pause
- **THEN** it displays as paused and its stored state is unchanged

### Requirement: A unit's summary holds all its wait figures

When a change is archived, each unit's summary SHALL carry `slot_wait_ms`, `pause_wait_ms` and `review_wait_ms`, review being split into a person's, rounds' and checks'. A summary written before this SHALL still load.

#### Scenario: Archiving

- **WHEN** a change is archived
- **THEN** every unit's summary has the three figures, none null for a unit that had the wait

#### Scenario: An older summary

- **WHEN** the ledger holds a summary with null wait figures
- **THEN** it loads and reads as absent

### Requirement: Every agent call writes exactly one ledger row

On every path a call can take, new, resumed or continued, under every runtime, an agent call SHALL write exactly one ledger row.

#### Scenario: Each path

- **WHEN** a call is made on each path
- **THEN** one row exists per call
