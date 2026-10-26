## ADDED Requirements

### Requirement: E2e-test test time is exported as bounded histograms

When telemetry is enabled the framework SHALL record each e2e-test test entry's duration as the histogram `abk.e2e.test.duration`, and its split as
`abk.e2e.test.time`, in seconds, with attributes marker, test file and phase (and cause, and role for agent time) and never a unit id, change name
or test name. It SHALL write one ledger row of kind `test_time` for each entry, carrying the unit, the change and the full test id, which readers that
do not know the kind SHALL skip. Exporting SHALL NOT affect a run, and a run with no entries SHALL record nothing.

#### Scenario: A test's phases are recorded

- **GIVEN** an e2e-test run with a call of 14 minutes in `tests/e2e/test_x.py`
- **WHEN** its result is built with telemetry enabled
- **THEN** the duration histogram has a sample with the marker, that file and phase `call`
- **AND** no attribute holds a unit id, change name or test name

#### Scenario: The split is exported

- **GIVEN** an entry whose split gives agent time for `implement`, checks and other
- **WHEN** it is recorded
- **THEN** the time histogram has a sample for each cause, with the role on the agent one only

#### Scenario: The ledger row

- **WHEN** an entry is recorded
- **THEN** a `test_time` row carries the unit, change, marker, test, phase and milliseconds, and the ledger's reader skips it

#### Scenario: Telemetry off

- **WHEN** telemetry is disabled
- **THEN** the ledger rows are written and nothing is exported

#### Scenario: An export that fails

- **WHEN** the export raises
- **THEN** the run is not failed and the result is posted as before
