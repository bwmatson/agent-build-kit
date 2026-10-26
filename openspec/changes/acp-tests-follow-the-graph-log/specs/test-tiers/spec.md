## ADDED Requirements

### Requirement: The live-agent tests read the log the engine writes

Tests that check a unit's progress through its run log SHALL match the lines the
current engine writes, using the engine's own node names, so that a change of
engine or of log wording fails them where they are, not at a later tier. A
failing e2e-test SHALL write the tail of its failure output to the unit's run
log.

#### Scenario: A unit built through a real agent

- **WHEN** the live-agent build test runs against the graph engine
- **THEN** it finds the review round, the first agent step and the agent's
  progress lines inside it, and passes

#### Scenario: E2e-test fails

- **WHEN** a unit's e2e-test run fails
- **THEN** the run log carries the tail of the failing output as well as the
  words "e2e-test failed"
