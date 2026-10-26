## ADDED Requirements

### Requirement: A toolchain profile says whether its test runner collects a file

A toolchain profile SHALL answer `collects_path(path)`: whether the profile's test runner, by its default rules, collects tests from the file at `path`. It SHALL be distinct from `is_test_path`, which says whether a file is on the test side and is unchanged. For the python-uv profile it SHALL be true when the file's own name, wherever the file is, matches `test_*.py` or `*_test.py`, and false for every other file, including `conftest.py` and a helper module under `tests/`. For the node-npm profile it SHALL give the same answer as that profile's `is_test_path`.

#### Scenario: Python collects test_ and _test modules

- **GIVEN** the python-uv profile
- **WHEN** `collects_path` is asked about `tests/pipeline/test_x.py`, `tests/pipeline/x_test.py` and `pkg/test_y.py`
- **THEN** each is true

#### Scenario: Python does not collect helpers or conftest

- **GIVEN** the python-uv profile
- **WHEN** `collects_path` is asked about `tests/integration/replay_unit_build.py`, `tests/conftest.py` and `tests/helpers.py`
- **THEN** each is false, while `is_test_path` is still true for each

#### Scenario: Node answers as it did

- **GIVEN** the node-npm profile
- **WHEN** `collects_path` is asked about `src/a.test.ts`, `src/__tests__/b.ts` and `src/c.ts`
- **THEN** it is true, true and false, the same as `is_test_path`
