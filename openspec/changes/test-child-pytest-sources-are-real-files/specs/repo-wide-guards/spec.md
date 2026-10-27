## ADDED Requirements

### Requirement: A new test module does not build a child pytest's source as a string

A meta-test over the tracked test sources, read through `tests/tracked_files.py`, SHALL fail a module that holds a string constant defining a test, a fixture or a pytest hook and also calls a function that runs or collects such a source, unless the module is listed in the guard's allow-list with its reason. The allow-list SHALL name only modules that match, so a module that has moved to real files under `tests/child_modules/` fails the guard until its entry is removed. The files below `tests/child_modules/` SHALL be exempt.

#### Scenario: A new module with a source in a string

- **GIVEN** a new test module that passes a string defining `def test_x():` to `pytester.makepyfile` and runs it
- **WHEN** the meta-test runs
- **THEN** it fails naming the file and the line

#### Scenario: A string that is only analysed

- **GIVEN** a test module with a string defining `def test_x():` that it only parses with `ast`
- **WHEN** the meta-test runs
- **THEN** it passes the module

#### Scenario: A migrated module still listed

- **GIVEN** a module in the allow-list whose strings have moved to files
- **WHEN** the meta-test runs
- **THEN** it fails naming the stale entry
