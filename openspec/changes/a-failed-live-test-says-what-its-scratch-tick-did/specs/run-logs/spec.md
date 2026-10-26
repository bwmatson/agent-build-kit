## ADDED Requirements

### Requirement: A failed live test can be diagnosed from the saved e2e log

The saved output of an e2e-test run SHALL hold, for each failed or errored live test with a scratch installation, the test's `SCRATCH STATE` section,
so a person reading only the file named in the result sees what the scratch tick printed and what state it left. The section SHALL be redacted as
the file is, and the pipeline SHALL NOT keep the scratch installation or any copy of its files after the run.

#### Scenario: Diagnosing a failure from the file alone

- **GIVEN** a live test that failed because its tick built nothing
- **WHEN** the file named by the result is read
- **THEN** it holds the tick's output, each unit's wait reason and the pause marker, and the scratch directory is gone

#### Scenario: The result text points to the file

- **GIVEN** a failed live test whose section is longer than the result's cut
- **WHEN** the result is built
- **THEN** the cause hints line reaches the failed test's digest through the failure message, and the result names the file that holds the whole section
