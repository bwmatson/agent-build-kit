# test-stubs Specification

## Purpose
TBD - created by archiving change tests-are-stubbed-checked-and-committed-per-group. Update Purpose after archive.

## Requirements

### Requirement: A tests commit in a stubbed build passes lint, format and types

When the build is stubbed, the test step SHALL write, beside the tests of a task group, the stubs the tests import: signatures whose
body only raises `NotImplementedError`, and model fields, with no logic. The files it wrote SHALL pass the profile's lint, format and
type checks before the tests commit is made. A build is stubbed when `builders.per_group_commits` is on and the unit's toolchain
profile supports stubs.

#### Scenario: A test imports a function that does not exist yet

- **GIVEN** a stubbed build and a group whose test imports `normalize_key` from a module that does not have it
- **WHEN** the test step finishes
- **THEN** the module holds a `normalize_key` whose body only raises `NotImplementedError`, with a signature the type checker accepts at
  the call in the test

#### Scenario: Not a stubbed build

- **GIVEN** the setting is off
- **WHEN** the test step runs
- **THEN** its prompt, its checks and its commit are as they were before this change

### Requirement: A stubbed tests commit is red for the right reason

In a stubbed build the red run at a tests commit SHALL be accepted only when every failing test failed by an assertion or by
`NotImplementedError` raised in the test body or by a fixture at setup. A test that fails with an import error, a missing module, a
missing attribute, a collection failure or a type error SHALL be rejected, naming the test and the reason, since a stub is missing
and the implementation would not make the test mean anything. A test that passes at the tests commit SHALL still be rejected.

#### Scenario: An assertion against a stub

- **GIVEN** a test calling a stub that raises `NotImplementedError`
- **WHEN** the red run is read for a stubbed build
- **THEN** it is accepted

#### Scenario: A missing attribute

- **GIVEN** a test that fails with `AttributeError` because the module has no such name
- **WHEN** the red run is read for a stubbed build
- **THEN** it is rejected naming the test, and for a build that is not stubbed it is accepted as before

#### Scenario: A passing test

- **WHEN** a test passes at its tests commit
- **THEN** the run is rejected, stubbed or not

### Requirement: The push gate's clean check includes types for a stubbed build

For a stubbed build the push gate SHALL run, at each tests commit, the profile's lint, format and type checks, and a tests commit
that fails any of them SHALL be refused naming the commit. For a build that is not stubbed the check SHALL be lint and format as
before. The python-uv profile's type check SHALL be its pre-commit type hook and the node-npm profile's SHALL be `tsc --noEmit` in
the project.

#### Scenario: A type error in a stub

- **GIVEN** a stubbed build whose tests commit has a stub with a return type the test contradicts
- **WHEN** the push gate runs
- **THEN** the branch is refused, naming the commit and the type checker's output

#### Scenario: A cached result from the other mode

- **GIVEN** a tests commit whose lint-and-format result was cached by an unstubbed run
- **WHEN** the push gate runs for a stubbed build
- **THEN** the checks run again, with types

### Requirement: A profile declares whether it supports stubs

A toolchain profile SHALL declare whether it supports stubs, and a profile that does not declare it SHALL be treated as not
supporting them. The python-uv and node-npm profiles SHALL support them. A unit whose profile does not support them SHALL be built
with one tests commit and one implementation commit, the checks of today and no check-and-fix loop, whatever the setting.

#### Scenario: A profile that does not support stubs

- **GIVEN** the setting is on and a unit whose profile declares no support
- **WHEN** the unit is built
- **THEN** it has one tests commit and one implementation commit, and the gate's clean check skips types

#### Scenario: The built-in profiles

- **WHEN** the python-uv and node-npm profiles are asked
- **THEN** each supports stubs
