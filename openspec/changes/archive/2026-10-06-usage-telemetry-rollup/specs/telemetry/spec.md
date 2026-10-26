## ADDED Requirements

### Requirement: The ledger's totals are exported as bounded metrics

When telemetry is enabled the framework SHALL export cost, tokens by kind, node
duration and wait durations from the same records it writes to the ledger, with
attributes of bounded cardinality (repository, tier, node, role, model, wait bucket,
source) and never unit ids or change names, and its dashboard SHALL show them.
Exporting SHALL NOT affect a run.

#### Scenario: An agent call is recorded

- **WHEN** an agent call is written to the ledger with telemetry enabled
- **THEN** its cost and tokens are added to the metrics with role and model attributes
- **AND** no metric attribute holds a unit id or change name

#### Scenario: Telemetry off

- **WHEN** telemetry is disabled
- **THEN** the ledger is written as before and nothing is exported
