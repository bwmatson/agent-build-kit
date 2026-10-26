## ADDED Requirements

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
