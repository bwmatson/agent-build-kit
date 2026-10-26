## MODIFIED Requirements

### Requirement: The gate has bounded exemptions and a bounded scope

The gate SHALL NOT hold a unit of the fix change itself or a unit that already waits on it. A unit SHALL be exempt only from the fix change
that its own change is, or that it already waits on, and SHALL be held by any other open fix change recorded for its repo. A record SHALL hold
only the units of the repo whose suite holds the failing test, and only a run that would execute a test of the failing test's runtime group:
a record of `base` holds every run, a record of a runtime holds a run that executes that runtime's tests, and a run that leaves a runtime out
(because it is blocked, or because it runs another group alone) SHALL NOT be held by that runtime's record.

#### Scenario: The fix change's own unit

- **GIVEN** an open fix change for a base failure
- **WHEN** a unit of that fix change reaches e2e-test
- **THEN** it runs e2e-test and gains no `Needs:` line

#### Scenario: A unit already waiting on the fix

- **GIVEN** a unit with a `Needs:` line on the open fix change
- **WHEN** it reaches e2e-test
- **THEN** it runs e2e-test and is not parked again

#### Scenario: A unit of one fix with another fix open

- **GIVEN** open fix changes A and B for two base failures of one repo
- **WHEN** a unit of fix A reaches e2e-test
- **THEN** it is held by fix B and gains a `Needs:` line on B only

#### Scenario: Another repo

- **GIVEN** an open fix change for a base failure in one repo
- **WHEN** a unit of a different repo reaches e2e-test
- **THEN** it runs e2e-test and gains no `Needs:` line

#### Scenario: A runtime's failure holds only the runs that execute it

- **GIVEN** an open fix change recorded for a failing `acp` test, and a full-scope run that leaves `acp` out because it is blocked or that runs `claude_code` alone
- **WHEN** a unit reaches the e2e-test step
- **THEN** it runs e2e-test and gains no `Needs:` line, while a full-scope run that executes `acp` tests is held by the same fix change
