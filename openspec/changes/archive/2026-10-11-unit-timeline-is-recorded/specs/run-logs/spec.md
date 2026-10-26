## ADDED Requirements

### Requirement: The decision log and old unit logs are bounded

The pipeline SHALL keep the decision log within a configured size, dropping its oldest lines, and SHALL remove a unit's log older than a configured number of days only after the unit's summary has been written to the ledger. A unit without a summary SHALL keep its log. Archiving a change SHALL still remove its logs.

#### Scenario: The log grows past its size

- **WHEN** the decision log exceeds its limit
- **THEN** the newest lines are kept

#### Scenario: An old log with a summary

- **WHEN** a unit's log is older than the limit and its summary exists
- **THEN** the log is removed

#### Scenario: An old log without a summary

- **WHEN** a unit's log is older than the limit and has no summary
- **THEN** it is kept
