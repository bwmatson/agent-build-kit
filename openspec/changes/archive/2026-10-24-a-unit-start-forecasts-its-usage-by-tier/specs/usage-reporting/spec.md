## ADDED Requirements

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
