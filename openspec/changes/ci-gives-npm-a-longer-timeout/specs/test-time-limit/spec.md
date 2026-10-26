## ADDED Requirements

### Requirement: A test can carry its own time limit

A test marked `time_limit(<seconds>)` SHALL be held to that many seconds on its setup, call and teardown, in place of the default `--test-time-limit`, and
fail with "test exceeded the time limit of <n> seconds" when it passes it. Every test without the marker, and the e2e limit of a `local_stack` test, SHALL
be as before. The marker SHALL be registered, so `--strict-markers` accepts it. The vitest integration test SHALL carry `time_limit(180)`.

#### Scenario: A marked test runs past the default

- **GIVEN** a test with `time_limit(5)` that takes 2 seconds under `--test-time-limit 1`
- **WHEN** it runs
- **THEN** it passes

#### Scenario: A marked test runs past its own limit

- **GIVEN** a test with `time_limit(1)` that takes 3 seconds
- **WHEN** it runs
- **THEN** it fails with "test exceeded the time limit of 1 seconds"

#### Scenario: Other tests keep the default

- **GIVEN** an unmarked test beside a marked one, under `--test-time-limit 1`
- **WHEN** the unmarked test takes 2 seconds
- **THEN** it fails at 1 second
