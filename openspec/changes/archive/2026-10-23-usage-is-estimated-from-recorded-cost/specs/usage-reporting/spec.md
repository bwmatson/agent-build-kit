## MODIFIED Requirements

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
