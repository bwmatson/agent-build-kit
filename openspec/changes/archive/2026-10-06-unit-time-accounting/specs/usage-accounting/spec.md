## ADDED Requirements

### Requirement: A unit's time is recorded as durations by kind

The pipeline SHALL record, in the accounting ledger, the start, end and duration of
each node a unit runs, the time a ready unit waits for a slot, the time it is paused
for the usage window, and the duration of each tier 1 command, all with UTC stamps
and the unit, change, node, round and a wait bucket. Time a pull request waits in
review SHALL be derivable from the unit's state history. Recording SHALL NOT affect
a run.

#### Scenario: A unit waits for a slot

- **GIVEN** more ready units than free slots
- **WHEN** a unit is submitted and later starts
- **THEN** a record carries the time between, with bucket `slot`

#### Scenario: A usage pause between steps

- **WHEN** the usage guard interrupts a unit before an agent step and a later tick
  resumes it
- **THEN** a record carries the time between, with bucket `usage_pause`

#### Scenario: A node that raises

- **WHEN** a node raises
- **THEN** its span is still recorded, with the failure outcome

#### Scenario: Tier 1

- **WHEN** a unit's tier 1 command runs for 45 seconds
- **THEN** a record carries that duration under its command
