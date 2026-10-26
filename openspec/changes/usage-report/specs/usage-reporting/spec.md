## ADDED Requirements

### Requirement: Token and time use can be reported by any grouping

The framework SHALL report, from the accounting ledger and the unit store, tokens by
kind, cost and time by bucket grouped by unit, change, node, role, model, repository
or day, filtered by date, change or unit, as a table or JSON. Each figure SHALL show
its source. Estimated figures SHALL be shown apart from measured ones and left out of
totals unless asked for. A figure that was never recorded SHALL read as absent, not
zero.

#### Scenario: A change's cost by node

- **WHEN** the report is grouped by node for one change
- **THEN** each node's calls, tokens, cost and time sum to the change's total

#### Scenario: Estimated and measured figures

- **GIVEN** a unit with some estimated calls
- **WHEN** the report runs
- **THEN** the estimates appear in their own column and the totals exclude them

#### Scenario: A figure never recorded

- **WHEN** a runtime reported no cost
- **THEN** the report shows it as absent

### Requirement: A summary page and archive keep the totals

The framework SHALL write a summary page of per-change totals and the most expensive
units when the unit store is written, without that write ever failing the store. When a
change is archived its detail records SHALL be rolled into one summary record per unit
before they are pruned, and the report SHALL read summaries and detail alike.

#### Scenario: A change is archived

- **WHEN** a change is archived
- **THEN** its detail records are replaced by one summary per unit
- **AND** the report's totals for the change are unchanged

#### Scenario: The page cannot be written

- **WHEN** the summary page's directory is unwritable
- **THEN** the unit store write succeeds and one line reports it
