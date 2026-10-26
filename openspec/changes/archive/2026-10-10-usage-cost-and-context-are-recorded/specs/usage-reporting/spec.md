## ADDED Requirements

### Requirement: Cost in every report, summary and metric is the sum of incremental figures

Every cost total, by unit, change, repository, day, node, role or model, the figures written into summary records at
archive, the usage view the web UI serves and the cost counter SHALL be the sum of each call's `incremental_usd`. The
report SHALL show per session the final cumulative figure beside the sum of its increments and SHALL flag a session whose
increments do not equal it. It SHALL count and list legacy rows and show their legacy total on a line of its own, apart
from the cost total. A call with no incremental figure SHALL add nothing to a cost total.

#### Scenario: A unit's cost

- **GIVEN** a unit whose session made three calls with increments 2.63, 2.86 and 7.69 and a final cumulative of 13.18
- **WHEN** the report is grouped by unit
- **THEN** the unit's cost is 13.18

#### Scenario: A session that does not add up

- **GIVEN** a session whose increments sum to less than its final cumulative
- **WHEN** the report is built
- **THEN** the session is flagged

#### Scenario: Legacy rows

- **GIVEN** a ledger with two legacy rows
- **WHEN** the report is built
- **THEN** the two rows are counted and listed and their legacy total is shown apart from the cost total

#### Scenario: A summary at archive

- **WHEN** a change with corrected rows is archived
- **THEN** its summary's cost is the sum of the increments

#### Scenario: The cost counter

- **WHEN** a call is recorded
- **THEN** the cost counter is raised by its `incremental_usd`, and by nothing when that is absent

#### Scenario: A call whose figure is unknown

- **GIVEN** a call with basis `unknown`
- **WHEN** the report is built
- **THEN** it adds nothing to the cost total and is counted among the unknown

### Requirement: The report shows context use per step and per session

`abk report --context` SHALL show, per step kind, the mean and the 90th percentile of the context added, the compaction
count and the end fill as used over max; per session the growth across its steps; and the steps that add the most. The
peak SHALL be shown only where it differs from the end fill. A call with no context figures SHALL be counted as unknown and
left out of the means. Telemetry SHALL carry the used and max window of each call as gauges and the compactions as a
counter.

#### Scenario: End fill

- **GIVEN** steps that ended at 142k of a 200k window
- **WHEN** the report is built with `--context`
- **THEN** the end fill reads `142k / 200k`

#### Scenario: Growth in a session

- **GIVEN** a session of four steps
- **WHEN** the report is built with `--context`
- **THEN** its rows show the fill after each step in order

#### Scenario: The steps that add the most

- **WHEN** the report is built with `--context`
- **THEN** the steps are listed by the context they added, largest first

#### Scenario: A peak above the end

- **GIVEN** a step that peaked at 195k and ended at 80k
- **WHEN** the report is built with `--context`
- **THEN** its peak is shown beside its end fill

#### Scenario: Rows with no context

- **GIVEN** rows written before context was recorded
- **WHEN** the report is built with `--context`
- **THEN** they are counted as unknown and do not enter the means

#### Scenario: The gauges

- **WHEN** a call with context figures is recorded with telemetry on
- **THEN** the used and max gauges and the compaction counter are exported with the same bounded attributes as the cost
