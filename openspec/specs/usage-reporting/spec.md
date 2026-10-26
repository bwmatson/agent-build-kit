# usage-reporting Specification

## Purpose
TBD - created by archiving change archive-keeps-breakdown. Update Purpose after archive.

## Requirements

### Requirement: An archived change keeps its breakdown by node, role and model

When a change is archived, the summary record that replaces each unit's usage detail SHALL keep the
unit's calls, tokens, cost and times broken down by node, role and model (and usage source), and the
sum of the breakdown SHALL equal the record's totals. A report grouped by node, role or model SHALL
read the breakdown, so archived work is split as live work is and no row stands for archived work as a
whole. The roll-up SHALL NOT write a summary without a breakdown, and rolling a change up again SHALL
give the same record.

#### Scenario: A report by node after archive

- **GIVEN** a change whose units made calls at several nodes, then archived
- **WHEN** the report is grouped by node
- **THEN** each node shows its own calls, tokens, cost and times
- **AND** no row stands for archived work as a whole

#### Scenario: Totals are unchanged

- **WHEN** a change is archived
- **THEN** the totals by unit, change, repository and day are the same as before

#### Scenario: Waiting without a call

- **GIVEN** a node that spent time waiting for a slot and made no agent call
- **WHEN** its change is archived
- **THEN** the report by node still shows that wait on the node

#### Scenario: Rolled up twice

- **WHEN** a change that has been rolled up is rolled up again
- **THEN** its records are unchanged

### Requirement: A summary from an older ledger still loads

A summary record with no breakdown SHALL still be read, contribute its totals to every grouping that
does not need a breakdown, and be shown under one label that says it has none. Merging it with new
detail for the same unit SHALL keep its totals.

#### Scenario: A ledger written before breakdowns

- **GIVEN** a ledger containing a summary with no breakdown
- **WHEN** the report is built
- **THEN** its totals are included under one labelled row in the node, role and model views

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

### Requirement: Wall time is reported by cause

The framework SHALL report, by `abk report --waits`, each unit's wall time by cause (planned blocked, planned ready, running in the agent, in checks, in other work, in review for a person, in review rounds, paused, failed), the hours the pipeline ran nothing split into a full queue and room to spare, and the estimate ratio per kind of unit when estimates exist, by unit or by day and as JSON. The causes SHALL sum to the wall time, and a figure never recorded SHALL read as absent.

#### Scenario: The recorded analysis

- **GIVEN** a recorded fixture of 72 merged units
- **WHEN** the waits report runs
- **THEN** it shows 1,343 h planned, 172 h in review, 93 h running and 11.6 h of agent calls
- **AND** it shows 47 of 87 hours with nothing running, 17 with a full queue and 30 with room

#### Scenario: Regrouping

- **WHEN** the report is grouped by unit and by day
- **THEN** both give the same total

#### Scenario: No records

- **WHEN** a unit has no wait records
- **THEN** its causes read as absent

### Requirement: Calls with no unit are shown as pipeline overhead

`abk report` and the usage page SHALL show the rows that have no unit as a `pipeline overhead` section with one line per node, calls,
tokens, cost and time as for any row, in the view by unit. In the views by node, role, model, change, repository and day they SHALL be grouped as any
row is, a missing change or repository under the report's label for an absent value. Every total SHALL include them, so a grouping's sum equals the ledger's. The section SHALL state the total cost of its rows and the share of the ledger's cost
it is, because the usage estimate counts that cost.
A row with a unit but a node outside the unit graph, as a `restack` row is, SHALL be shown on its unit and on its node. The
wall-time report SHALL NOT add such a row's duration to a unit's agent time.

#### Scenario: Overhead in the report by unit

- **GIVEN** rows for `plan`, `track_health` and a unit's `implement`
- **WHEN** the report is grouped by unit
- **THEN** the unit has its row and a `pipeline overhead` section has one line for `plan` and one for `track_health`

#### Scenario: Totals

- **WHEN** the report is grouped by unit, by node and by day
- **THEN** each grouping's cost sums to the same total, and that total includes the overhead

#### Scenario: A restack row

- **GIVEN** a `restack` row for a unit
- **WHEN** the report is grouped by unit and by node
- **THEN** the cost is on the unit's row and on the `restack` node's row, and not in the overhead section

#### Scenario: The usage page

- **WHEN** the usage page is served over a ledger with overhead rows
- **THEN** it shows the same `pipeline overhead` line for each node

#### Scenario: Wall time

- **GIVEN** a unit with a `restack` row
- **WHEN** the waits report is built
- **THEN** the unit's causes still sum to its wall time, and the row's duration is not counted as the unit's agent time

#### Scenario: A change archived

- **WHEN** a change is archived and the ledger holds overhead rows with no change
- **THEN** those rows are left as they are and the report's totals do not move

#### Scenario: The share of the cost

- **GIVEN** overhead rows costing $21.86 in a ledger whose rows cost $354.00 in all
- **WHEN** the report is grouped by unit
- **THEN** the `pipeline overhead` section states $21.86 and 6% of the ledger's cost

### Requirement: The report can group by review tier and shows the forecast against what was spent

`abk report --by tier` SHALL group the ledger's agent rows by the review tier planned for each row's unit (the verdict record's
`planned_estimate`, else the unit's stored review tier, else `(none)`), and SHALL NOT group by the ledger's own `tier` field, which is the test kind. For
each review tier it SHALL show the units, the dollars forecast for them when they were admitted (from the forecast rows), the dollars
spent (the sum of their incremental figures, as every report sums), the ratio of spent to forecast, the number of units that spent
more than their forecast, and the spend by role and node. A unit with no forecast row SHALL be counted as unforecast, shown apart,
and SHALL NOT be treated as a forecast of zero in the ratio. The forecast of a tier SHALL be the sum of its units' forecasts, as
recorded, whatever the settings are now. `--json` SHALL carry the same figures, and every other grouping SHALL be as it was.

#### Scenario: Forecast against actual per tier

- **GIVEN** `auto` units forecast at $2.55 each that spent $2.00, $2.60 and $3.40 and `full` units forecast at $3.42 each that spent $3.00 and $4.00
- **WHEN** `abk report --by tier` runs
- **THEN** the `auto` row shows three units, $7.65 forecast, $8.00 spent, a ratio of 1.05 and one unit over its forecast, and the `full` row two units, $6.84 forecast, $7.00 spent, 1.02 and one over

#### Scenario: A unit with no forecast

- **GIVEN** a unit admitted before forecasts were recorded
- **WHEN** the report runs
- **THEN** it is counted under unforecast in its tier and is not in the ratio

#### Scenario: Spend by role

- **GIVEN** `full` units whose rows have the review and rework nodes
- **WHEN** the report runs
- **THEN** the `full` row's spend is shown by role and node

#### Scenario: The ledger's tier is not the grouping

- **GIVEN** rows with `tier` of `unit-test` and `e2e-test`
- **WHEN** `abk report --by tier` runs
- **THEN** no row is headed `unit-test` or `e2e-test`; the rows are under `auto`, `light`, `full` or `(none)`

#### Scenario: A unit with no tier

- **GIVEN** a unit with no verdict record and no stored review tier
- **WHEN** the report runs
- **THEN** its rows are under `(none)`

#### Scenario: Other groupings are unchanged

- **WHEN** `abk report --by node` runs
- **THEN** its output is what it was before this change

#### Scenario: JSON

- **WHEN** `abk report --by tier --json` runs
- **THEN** each tier carries its units, forecast, spent, ratio, unforecast count and spend by role and node
