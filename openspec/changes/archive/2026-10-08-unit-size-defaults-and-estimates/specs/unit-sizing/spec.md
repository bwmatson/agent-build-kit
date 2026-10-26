## MODIFIED Requirements

### Requirement: A workspace configures a ceiling on a unit's size

The workspace SHALL configure the largest number of changed lines one unit may
carry, defaulting to 750, and that ceiling SHALL be required to exceed the
floor on unit size, which defaults to 400. A workspace that sets either value
keeps it. A configuration whose floor is at or above its ceiling SHALL fail to
load, naming both values.

#### Scenario: The default

- **WHEN** a workspace configures no ceiling
- **THEN** the ceiling is 750 changed lines and the floor is 400

#### Scenario: A floor above the ceiling

- **WHEN** a workspace sets a floor at or above the ceiling
- **THEN** loading the configuration fails, naming both values, rather than
  producing plans that cannot satisfy either

## ADDED Requirements

### Requirement: The planner is told what an estimate counts

The planner's instructions SHALL define an estimate as the additions plus deletions in every
file a group changes, including tests, docs, fixtures and the changelog and excluding
generated files, SHALL tell it to count the removed lines of a group that removes or
rewrites code, and SHALL tell it to estimate high when unsure.

#### Scenario: A group that deletes code

- **GIVEN** a group that removes an existing module and replaces it
- **WHEN** the planner is instructed
- **THEN** its instructions tell it to count the removed lines as well as the added ones

### Requirement: A unit records its actual size beside its estimate

A unit with a pull request SHALL record the pull request's actual changed lines, excluding
generated files, when the pull request is opened and again whenever a push updates it, and
SHALL log, mark in the graph page and list in the status when the actual size exceeds the
ceiling. The ceiling SHALL NOT block a unit from landing.

#### Scenario: A unit lands over the ceiling

- **GIVEN** a unit estimated at 600 lines whose pull request changes 1,400
- **WHEN** the pull request is opened
- **THEN** the unit records 1,400 beside its estimate, and its log, the page and the status
  say it is over the ceiling

#### Scenario: A rework changes the size

- **WHEN** a push after a rework changes the pull request's size
- **THEN** the recorded actual size is updated

#### Scenario: A lockfile

- **WHEN** a pull request includes a lockfile's changes
- **THEN** they are not counted in the actual size
