## ADDED Requirements

### Requirement: A cancelled check is re-run, not reworked

The poller SHALL NOT treat a cancelled check as a failing check, and SHALL NOT
send a unit back for rework because of one. When a unit's head has cancelled
checks, the runner SHALL ask the host to run them again, without an agent, up to
a bounded number of times per head commit. When the bound is spent, the unit
SHALL stay in review with the reason recorded in its log, and SHALL NOT be
reworked. A timed-out check remains a failure. A pull request with a cancelled
check and a failing one SHALL be reworked for the failing one.

#### Scenario: The host cancels checks that never started

- **GIVEN** a unit in review whose checks on its head are all cancelled
- **WHEN** a poll finds them
- **THEN** no rework is requested
- **AND** the host is asked to run the cancelled checks again

#### Scenario: The checks keep being cancelled

- **GIVEN** a head commit whose checks were re-run up to the bound and cancelled
  again
- **WHEN** a poll finds them
- **THEN** no further re-run is asked for
- **AND** the unit's log says the host keeps cancelling the checks

#### Scenario: A check timed out

- **GIVEN** a unit whose check timed out
- **WHEN** a poll finds it
- **THEN** the unit is reworked, as for any failing check

#### Scenario: A mixed outcome

- **GIVEN** one check failed and another was cancelled
- **WHEN** a poll finds them
- **THEN** the unit is reworked for the failure and the cancelled check is
  re-run
