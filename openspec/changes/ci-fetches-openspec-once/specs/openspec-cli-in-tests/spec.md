## ADDED Requirements

### Requirement: The integration job fetches the pinned OpenSpec CLI once

The integration job of the kit's CI SHALL, before it runs its tests, fetch and start the pinned OpenSpec CLI through `npx` in a step of its own, with at
most 3 attempts, a timeout, and `npx`'s cache cleared between attempts, and SHALL fail that step with the message "the OpenSpec CLI is not installed" when
every attempt fails. The other jobs SHALL NOT have the step, and the suite's per-test time limit SHALL NOT be raised.

#### Scenario: The first fetch fails and the second succeeds

- **GIVEN** an `npx` that fails once and then succeeds
- **WHEN** the step's script runs
- **THEN** it ends with status 0 after two calls, with `npx`'s cache directory removed between them

#### Scenario: Every fetch fails

- **GIVEN** an `npx` that always fails
- **WHEN** the step's script runs
- **THEN** it makes exactly 3 calls, prints "the OpenSpec CLI is not installed" and ends with status 1

#### Scenario: The step sits before the tests in the integration job only

- **WHEN** the workflow is read
- **THEN** the `integration` job has the step after uv is set up and before the tests, with a timeout, and the `pre-commit` and `test` jobs do not have it

#### Scenario: The time limit is unchanged

- **WHEN** the integration job's test step is read
- **THEN** it runs `pytest -m integration` with no time-limit option

### Requirement: The pin is written in one place

The OpenSpec package name and version SHALL be written only where the kit defines them, in `openspec.py` and `settings.py`, and the workflow and its
scripts SHALL read them from there at run time.

#### Scenario: The workflow reads the pin from the settings

- **WHEN** the integration job's warm-up step is read
- **THEN** it takes the spec from `PACKAGE` and `settings.openspec_version`, and the workflow file and the script contain neither the package name nor the version string

#### Scenario: A hand-copied pin is caught

- **GIVEN** a workflow that spells the version
- **WHEN** the test runs
- **THEN** it fails naming the line

### Requirement: A test that needs the OpenSpec CLI fails once with one message when it cannot be run

An integration test that runs the OpenSpec CLI SHALL request a session fixture that runs the CLI's `--version` once, and SHALL fail with a message that
begins "the OpenSpec CLI is not installed", with the exit status and the last lines of the error, when the CLI cannot be started. A command of a test
that exits with status 127 SHALL be reported with the same message and not as a failure of what the test checks; any other status SHALL stay the test's own assertion.

#### Scenario: The CLI cannot be started

- **GIVEN** a runner that exits with status 127
- **WHEN** two integration tests that request the fixture run
- **THEN** both fail with the same first line, "the OpenSpec CLI is not installed", and a test that does not request it passes

#### Scenario: A later command exits 127

- **GIVEN** a test whose `validate` command exits with status 127
- **WHEN** its result is passed through `require`
- **THEN** the test fails with the same message and not with an assertion on the command's output

#### Scenario: A validation fails

- **GIVEN** a command that exits with status 1 because the change does not validate
- **WHEN** its result is passed through `require`
- **THEN** the result is returned unchanged for the test to assert on

#### Scenario: A new integration file runs the CLI without the fixture

- **GIVEN** an integration test file that calls `openspec.run` and does not request the fixture
- **WHEN** the guard test runs
- **THEN** it fails naming the file
