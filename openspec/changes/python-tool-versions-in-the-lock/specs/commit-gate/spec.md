## ADDED Requirements

### Requirement: A Python repo's formatter, linter and type checker run from its lock

For a repo on the Python profile, the formatter, linter and type checker versions
SHALL be set by the project's dependency lock and nowhere else, and the commit
gate, unit-test and CI SHALL run those tools from the project's environment. The
hooks that run them SHALL NOT carry a separate version. A tool that is not a
project dependency SHALL keep the version its hook sets. The recommendations
the framework gives a new Python repo SHALL describe this arrangement, and
`abk doctor` SHALL warn when a tool has a version in both places.

#### Scenario: A repo set up from the recommendations

- **WHEN** `abk init` researches and proposes a Python repo's tooling
- **THEN** the formatter, linter and type checker are dependencies in the lock
- **AND** their hooks run the project's copy

#### Scenario: A tool pinned in both places

- **GIVEN** a repo whose dependency group pins a tool that a hook also runs from
  a repository at its own version
- **WHEN** `abk doctor` runs
- **THEN** it warns, naming both files

#### Scenario: A hook that can only fail

- **GIVEN** a hook that runs the project's copy of a tool the dependency group
  does not contain
- **WHEN** `abk doctor` runs
- **THEN** it warns that the hook cannot succeed

#### Scenario: A fresh clone

- **WHEN** a person commits in a fresh clone that has not been synced
- **THEN** the hook creates the environment from the lock and runs, rather than
  failing with a tool-not-found error
