## ADDED Requirements

### Requirement: Another tool's output is classified in one adapter and tested against recordings

Where a decision depends on another tool's output, the framework SHALL read that output
in one adapter per tool that returns a typed result, SHALL prefer the tool's structured
or machine-readable output over its prose where it has one, and SHALL test the adapter
against messages recorded from the real tool. Callers SHALL NOT read the tool's text.

#### Scenario: A push declined by a hook

- **GIVEN** a push the remote declines in a hook
- **WHEN** the push result is classified
- **THEN** it is reported as rejected by the remote and not as another writer's push

#### Scenario: A stale lease

- **GIVEN** a push whose lease no longer matches
- **WHEN** it is classified
- **THEN** it is reported as a stale lease

#### Scenario: A rate limit with structured fields

- **GIVEN** an agent CLI closing event flagged as an error with a rate-limit status
- **WHEN** the run's failure is classified
- **THEN** it is a rate limit without reading its prose

#### Scenario: A test failing for the wrong reason

- **GIVEN** a new test that fails with an import error
- **WHEN** the red check runs
- **THEN** it is rejected, because the report's exception type says so

#### Scenario: A tool changes its wording

- **WHEN** a recorded message no longer classifies as it did
- **THEN** a contract test fails
