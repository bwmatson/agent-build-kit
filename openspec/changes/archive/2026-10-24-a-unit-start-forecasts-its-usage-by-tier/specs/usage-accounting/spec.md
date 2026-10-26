## ADDED Requirements

### Requirement: A unit's forecast and each step admitted are recorded when the guard admits them

When the guard admits a unit's first agent step it SHALL append to `usage-forecasts.jsonl` in the state directory a forecast row with the
unit, its review tier and size band, the time, the forecast of each window in dollars and points, the dollars by role and node, and
whether the unit's history or the prior was used; and for every agent step it admits, a step row with the unit, node, round and time.
Rows SHALL be appended once however many times the same ask is repeated, SHALL be written under the lock the ledger uses, and a failure
to write one SHALL be logged and SHALL NOT refuse or fail the start. A line that cannot be parsed SHALL be skipped by every reader. With
`usage_forecast` off no row SHALL be written. These rows are not ledger rows and are never added to a cost.

#### Scenario: A unit's first step

- **GIVEN** a unit with no forecast row that is admitted
- **WHEN** the admission is recorded
- **THEN** one forecast row holds its tier, band, forecast per window in dollars and points, dollars by role and node, and whether the prior was used, and one step row holds its node, round and time

#### Scenario: A later step

- **GIVEN** a unit with a forecast row that is admitted to its next step
- **WHEN** the admission is recorded
- **THEN** a step row is appended and no second forecast row

#### Scenario: The same ask twice

- **GIVEN** a unit admitted at a gate that is asked again for the same step on the same reading
- **WHEN** the admission is recorded
- **THEN** one step row exists for it

#### Scenario: A write that fails

- **GIVEN** a state directory the record cannot be written in
- **WHEN** a unit is admitted
- **THEN** a line says so, the unit is admitted and no error is raised

#### Scenario: A half-written line

- **GIVEN** a record whose last line is cut off
- **WHEN** it is read
- **THEN** the line is skipped and the others are read

#### Scenario: Forecast off

- **GIVEN** `usage_forecast` false
- **WHEN** a unit is admitted
- **THEN** no row is written
