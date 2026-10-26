# e2e-own-test-selection Specification

## Purpose
TBD - created by archiving change e2e-selection-names-only-collected-files. Update Purpose after archive.

## Requirements

### Requirement: The own-test selection names only tests the suite collects

When the e2e-test step narrows a unit to its own tests, it SHALL name a touched test by identifier only when the profile's `collects_path` is true for the test's file. A file the runner does not collect by default, a helper module under `tests/` and `conftest.py` among them, SHALL NOT be named, whatever `def test_*` it holds. `is_test_path` SHALL remain what the push gate, verify and the unit-test step use. A custom `python_files` or `testpaths` in a repo's pytest configuration is not read; the default collection rules are the rules, and a test the repo's configuration collects but they do not is left to the whole marker run.

#### Scenario: A helper module with a test function is not named

- **GIVEN** a unit that adds `tests/integration/replay_unit_build.py` with `def test_the_unit_is_built` and a driver `tests/integration/test_replay.py` with `def test_driver`
- **WHEN** the e2e scope is decided
- **THEN** the ids are `tests/integration/test_replay.py::test_driver` only

#### Scenario: A test_ module is named

- **GIVEN** a unit that adds `tests/integration/test_replay.py` with `def test_a`
- **WHEN** the e2e scope is decided
- **THEN** `tests/integration/test_replay.py::test_a` is named

#### Scenario: A _test module is named

- **GIVEN** a unit that adds `tests/integration/replay_test.py` with `def test_a`
- **WHEN** the e2e scope is decided
- **THEN** `tests/integration/replay_test.py::test_a` is named

#### Scenario: conftest.py is not named

- **GIVEN** a unit that adds a `def test_fixture_check` to `tests/integration/conftest.py`
- **WHEN** the e2e scope is decided
- **THEN** nothing from `conftest.py` is named

#### Scenario: The node profile is unchanged

- **GIVEN** a node-npm project and a unit that adds `src/a.test.ts` and `src/__tests__/b.ts`
- **WHEN** the e2e scope is decided
- **THEN** both are selected as before

#### Scenario: A unit that touched only a helper selects nothing and says so

- **GIVEN** a unit whose only touched test file is `tests/integration/replay_unit_build.py`
- **WHEN** the e2e scope is decided
- **THEN** it has no runs and no ids, takes no stack lock, logs `e2e-test skipped: no e2e test added or changed` followed by the file left out, and its status says no e2e-test test ran
