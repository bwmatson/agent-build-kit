## ADDED Requirements

### Requirement: The port is the last step of the conflict step, in the same session

The port SHALL be the last step of the order a conflict is settled in, started only when the narrower steps have failed their checks. It
SHALL be a call of the session those steps ran in, and SHALL be told which of them were tried and what their checks said, in addition to
what it is told today. The accounting, its check and its bounded asks SHALL apply to it and SHALL NOT apply to a conflict the narrower
steps settled. A session that cannot be continued SHALL be replaced by a new one given the full prompt, with no error. A conflict the
port does not settle SHALL fail as it does today, with the outstanding tests on the unit's record.

#### Scenario: A conflict that needs a port escalates in the same session

- **GIVEN** a conflict whose first two steps failed their checks
- **WHEN** the port starts
- **THEN** it runs in the same session, the old work is kept under a reference and the branch is reset onto the new base, and the prompt says what was tried

#### Scenario: The accounting applies to the port only

- **GIVEN** a conflict settled by the first step
- **WHEN** the move completes
- **THEN** no decision is asked for any of the unit's tests

#### Scenario: The session is gone

- **GIVEN** a session the runtime cannot continue
- **WHEN** the port starts
- **THEN** it runs in a new session with its full prompt

#### Scenario: The port fails its accounting

- **WHEN** the accounting is still incomplete after its last ask
- **THEN** the unit fails with the outstanding tests on its record, as before
