## ADDED Requirements

### Requirement: Every agent call's reported usage is recorded with its unit

For each agent call the pipeline SHALL record the tokens by kind (input, output,
cache read, cache write), cost, turns, duration and session id the runtime
reports, together with the unit, change, repository, node, review round, role,
model and runtime, in an append-only ledger in the state directory. Each figure
SHALL carry its source (reported, estimated or none). A figure the runtime does not
report SHALL be recorded as absent and never as zero, and an estimate SHALL be
flagged and kept apart from measured figures. Recording SHALL NOT affect a run: a
failed write SHALL be dropped and reported once.

#### Scenario: A call on the Claude runtime

- **WHEN** a unit's review round completes on the Claude runtime
- **THEN** one record names the unit, node, round, role and model, carries the
  reported tokens, cost, turns and duration, and has source `reported`

#### Scenario: A runtime that reports nothing

- **WHEN** an ACP agent returns no usage
- **THEN** the record's figures are absent and its source is `none`, or its tokens
  are estimates flagged as such

#### Scenario: The ledger cannot be written

- **GIVEN** a state directory that cannot be written
- **WHEN** an agent call completes
- **THEN** the run continues unchanged and one line reports the failure

### Requirement: A resumed or re-run call is counted once

A node re-run after a kill, or continuing a resumed session, SHALL NOT double count:
the ledger's reader SHALL keep one record per unit, node, round and session.

#### Scenario: A node killed and re-run

- **GIVEN** a node whose call was recorded and which then ran again
- **WHEN** the ledger is read
- **THEN** that node and round count once

### Requirement: A change in the ACP payload cannot fail a run

The ACP runtime SHALL parse usage tolerantly, record whether the agent offers it, and
on a payload it cannot parse fall back to the next source and log once. A contract
test SHALL replay recorded payloads with and without usage and with an extra field.

#### Scenario: An unknown field

- **WHEN** a usage payload carries a field the runtime does not know
- **THEN** the known figures are recorded and the run is unaffected
