## ADDED Requirements

### Requirement: A unit whose step cannot reach the host is parked, not failed

When a step of a unit cannot complete because the code host is unavailable, the unit SHALL be
returned to planned with a host-unavailable cause, the failing step and the error text, SHALL be
readmitted by the running pass after a backoff that grows with each consecutive parking, and SHALL
resume at that step. A failure for any other reason SHALL fail the unit and SHALL record its error
text and step on the unit.

#### Scenario: The host is down when the pull request is opened

- **GIVEN** an approved, pushed unit whose pull request create is answered 500 on every attempt
- **WHEN** the step gives up
- **THEN** the unit is planned with the host-unavailable cause and the error text

#### Scenario: The host recovers

- **GIVEN** a parked unit whose backoff has elapsed and a host that answers
- **WHEN** the pass refreshes
- **THEN** the unit resumes at the step and the pull request opens

#### Scenario: Backoff grows

- **GIVEN** a unit parked for the third time
- **WHEN** the pass refreshes before its backoff has elapsed
- **THEN** the unit is skipped and the log says how long remains

#### Scenario: Another failure

- **WHEN** a step raises an error that is not the host being unavailable
- **THEN** the unit fails and its error text and step are on the unit

### Requirement: A unit whose work is already pushed resumes at the pull request step

A unit whose approved commit is its pushed head SHALL, when resumed after a failure of the pull
request step, go straight to that step, without running tier 2 again, without a review and without
reworking from saved feedback.

#### Scenario: A tier 2 unit

- **GIVEN** a tier 2 unit approved and pushed whose pull request step failed
- **WHEN** it is resumed
- **THEN** tier 2 does not run again

#### Scenario: A unit with saved feedback

- **GIVEN** a unit with saved feedback whose reworked commit is approved and pushed
- **WHEN** it is resumed after the pull request step failed
- **THEN** it does not go back to rework
