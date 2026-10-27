## ADDED Requirements

### Requirement: A test that drives a plugin in a child pytest holds the child's code in files

The code a test runs in a child pytest SHALL be held as Python files below `tests/child_modules/<scenario>/`, with the child's configuration file, and SHALL be copied into the test's own directory and run there in a subprocess with the plugin loaded by `-p`. A value the child needs SHALL reach it through the command line or an environment variable, never by formatting it into a source. The files SHALL NOT be collected by the repository's own pytest run, and ruff and pyrefly SHALL check them with the settings they already have for `tests/`. The time-limit tests of `tests/test_marked_time_limit.py` and `tests/test_e2e_time_limit.py` SHALL be held this way.

#### Scenario: The child's code is checked

- **GIVEN** a scenario file under `tests/child_modules/` with an unused import
- **WHEN** the pre-commit hooks run over the changed files
- **THEN** ruff names the file and the line

#### Scenario: The repo's own run does not collect the scenarios

- **GIVEN** the scenario folders under `tests/child_modules/`
- **WHEN** the suite is collected
- **THEN** no test id names a file under `tests/child_modules/`

#### Scenario: A value reaches the child without formatting

- **GIVEN** the blocking scenario of the marked-limit tests
- **WHEN** it is run with `CHILD_FIRE_FIRST_TIMER=1`
- **THEN** the first timer of each test fires at once and the test fails naming its limit, and the reading scenario, run without the variable, asserts the limits the hook armed

### Requirement: The marked time-limit tests do not depend on elapsed time

A test of `time_limit(<seconds>)` SHALL decide its outcome from the interval the hook armed, read through a recording timer in the child, and SHALL end a test that must run past its limit by firing the first timer at once. The child files of the marked-limit scenario SHALL NOT import `time` or call a sleep or a clock, and the converted tests SHALL pass on every run of the suite's parallel command.

#### Scenario: A clock call in a scenario file

- **GIVEN** a marked-limit scenario file that calls `time.monotonic()`
- **WHEN** the determinism test runs
- **THEN** it fails naming the file and the line

#### Scenario: The parallel suite command

- **WHEN** `pytest -n auto --maxprocesses=8` runs the converted tests twenty times in a row
- **THEN** every run passes
