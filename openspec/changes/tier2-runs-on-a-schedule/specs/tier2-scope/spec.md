## ADDED Requirements

### Requirement: How much of e2e-test a unit runs is a setting

The setting `e2e_unit_scope` SHALL be `own` or `full` and SHALL default to `own`. It SHALL be settable for all repos as `limits.e2e_unit_scope` and for
one repo as `repos.<name>.tests.e2e_unit_scope`; the repo's value, when set, SHALL win over the `limits` one. Any other value in either place SHALL be
refused when the configuration loads, naming the setting and the two values. `abk config --show` SHALL show the values set. Under `full` an e2e-test unit SHALL run the whole e2e-test
marker of its repo, exactly as it did before the setting existed.

#### Scenario: The default

- **GIVEN** a configuration with no `limits.e2e_unit_scope`
- **WHEN** it is loaded
- **THEN** the value is `own`, and `abk config --show` prints it

#### Scenario: A repo overrides the default

- **GIVEN** `limits.e2e_unit_scope: full` and one repo with `tests.e2e_unit_scope: own`
- **WHEN** units of each repo reach e2e-test
- **THEN** the repo's units run their own tests and the other repos' units run the whole marker

#### Scenario: Full restores the whole marker

- **GIVEN** `e2e_unit_scope` in effect for the repo as `full` and an e2e-test unit that adds one e2e-test test
- **WHEN** its e2e-test step runs
- **THEN** it runs the whole e2e-test marker of the repo, takes the stack lock, and the base run, the record and the fix flow work as they did

#### Scenario: A value that is not one of the two

- **GIVEN** `limits.e2e_unit_scope: some`, or `tests.e2e_unit_scope: some` on a repo
- **WHEN** the configuration is loaded
- **THEN** it is refused with a message naming the setting and the values `own` and `full`

### Requirement: Under own scope a unit runs the e2e-test tests it added or changed

Under `own` the e2e-test step SHALL run only the tests the unit's branch adds or changes against its base, the set unit-test repeats, selected by their
identifiers through the toolchain profile and kept under the e2e-test marker and the command's other options, one command for each project that has one
of them. A test that does not carry the marker SHALL NOT run. A project none of whose commands takes one of the identifiers SHALL run nothing. The scope
SHALL be decided before the stack lock is taken, by one function the e2e-test step and the open-fix gate both ask.

#### Scenario: Only the unit's own tests run

- **GIVEN** an e2e-test unit that adds a test and changes another in a repo whose marker selects forty tests
- **WHEN** its e2e-test step runs
- **THEN** one command per project runs those two identifiers with the marker, and the other thirty-eight tests do not run

#### Scenario: A changed test without the marker

- **GIVEN** a unit that changes a test that does not carry the e2e-test marker and adds none that does
- **WHEN** its e2e-test step runs
- **THEN** the test is not run, the command collects nothing, and the outcome is the one for a unit with no e2e-test test of its own

#### Scenario: Tests in more than one project

- **GIVEN** a repo with two projects and a unit that changes an e2e-test test in one of them
- **WHEN** the step runs
- **THEN** only that project's command runs, with identifiers relative to that project's directory

#### Scenario: One decision for the step and the gate

- **GIVEN** a unit about to run e2e-test
- **WHEN** the step and the open-fix gate each ask for the run's scope
- **THEN** both are given the same answer from one function, and it runs before the stack lock is taken

### Requirement: A unit with no e2e-test test of its own runs no e2e-test

An e2e-test unit that adds or changes no test that the e2e-test marker selects SHALL run no e2e-test command and SHALL NOT take the stack lock. Its run log
SHALL say that e2e-test was skipped because no e2e-test test was added or changed, and its status line and the status posted for its commit SHALL say that no
e2e-test test ran, not that the suite passed. The unit SHALL go on as a unit whose e2e-test passed.

#### Scenario: Nothing to run

- **GIVEN** an e2e-test unit whose branch changes no test
- **WHEN** its e2e-test step runs
- **THEN** no command runs, the lock is not taken, the run log says `e2e-test skipped: no e2e-test test added or changed`, and the unit goes on to its next step

#### Scenario: The status says nothing ran

- **GIVEN** a unit that ran no e2e-test test and pushes
- **WHEN** its e2e-test status is posted and `abk status` is read
- **THEN** each says that no e2e-test test ran, and neither says the e2e-test suite passed

#### Scenario: The lock is free for others

- **GIVEN** another unit holding the e2e-test lock
- **WHEN** a unit with no e2e-test test of its own reaches its e2e-test step
- **THEN** it does not wait for the lock

### Requirement: A run that cannot be narrowed runs the whole marker and says why

Under `own`, the e2e-test step SHALL run the whole marker and log the reason when the run cannot be narrowed safely: the repo runs e2e-test through its dev
stack script, the toolchain profile cannot select tests by identifier, the unit's tests cannot be listed, or the run has no base to list them against. A
failure to narrow SHALL NOT be read as a unit with no test of its own.

#### Scenario: The dev stack script

- **GIVEN** `own` and a repo with a dev stack script
- **WHEN** a unit that changes no test reaches its e2e-test step
- **THEN** the script's run is made as before, and the log says that e2e-test runs whole because the dev stack script runs it

#### Scenario: A profile that cannot select tests

- **GIVEN** `own` and a profile without selection by identifier
- **WHEN** a unit reaches its e2e-test step
- **THEN** the whole marker runs and the log names the profile and the reason

#### Scenario: The tests cannot be listed

- **GIVEN** `own` and a listing of the unit's tests that fails
- **WHEN** the step runs
- **THEN** the whole marker runs and the log says the unit's tests could not be listed, with the error, and the unit is not treated as having no test of its own

### Requirement: A failing own test fails the unit, and the failure flow is unchanged

A failure of a test an own run executed SHALL fail the unit as a failure of its own does today, with the output saved as feedback. The base run, the
classification, the record of pre-existing failures and their fix changes SHALL work as before on the failures they are given; the scope SHALL only
change which tests run.

#### Scenario: An own test fails

- **GIVEN** an own run in which one of the unit's own tests fails
- **WHEN** the step ends
- **THEN** the unit fails with the failure as feedback, no base run is made, and nothing is recorded as pre-existing

#### Scenario: A full run meets an untouched failing test

- **GIVEN** `full` and a failing test the unit did not touch that fails on the base too
- **WHEN** the step ends
- **THEN** it is recorded, gets its one fix change and parks the unit, as before this change

#### Scenario: A passing own run

- **GIVEN** an own run in which every selected test passes
- **WHEN** the step ends
- **THEN** the result is a pass of the tests it ran and says how many ran
