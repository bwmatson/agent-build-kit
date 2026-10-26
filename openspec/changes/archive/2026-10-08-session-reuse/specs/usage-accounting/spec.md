## MODIFIED Requirements

### Requirement: A resumed or re-run call is counted once

A node re-run after a kill SHALL NOT double count: the ledger's reader SHALL keep one record
per unit, node, round and call. A call that continues a session another node started, as
`fix_checks` continuing the build session does, SHALL be counted under the node that made
the call, and the session id SHALL be an attribute of the record, not part of its key, so one
session id may appear under several nodes.

#### Scenario: A node killed and re-run

- **GIVEN** a node whose call was recorded and which then ran again
- **WHEN** the ledger is read
- **THEN** that node and round count once

#### Scenario: A fix continuing the build session

- **GIVEN** `implement` and then `fix_checks` in one session
- **WHEN** the ledger is read
- **THEN** each node's spend is under its own node, and both records carry the session id
