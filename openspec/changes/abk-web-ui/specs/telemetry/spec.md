## ADDED Requirements

### Requirement: Every exported metric can be rebuilt from local records

For each metric the pipeline exports, the figures SHALL be recoverable from files the pipeline keeps
locally, whether or not telemetry is enabled. Ticks, pauses, review rounds, check failures and unit
outcomes SHALL be appended to a local record when they happen, and those records SHALL be kept when
a change is archived.

#### Scenario: Telemetry is off

- **GIVEN** telemetry disabled
- **WHEN** a tick, a pause and a check failure occur
- **THEN** each is appended to the local record

#### Scenario: A change is archived

- **GIVEN** records for the change's units
- **WHEN** the change is archived
- **THEN** the tick, pause, review round, check failure and unit records are not rolled up or removed

#### Scenario: A reader of the record

- **WHEN** the metrics page derives tick durations from local files
- **THEN** it gets the same durations the exported histogram counted
