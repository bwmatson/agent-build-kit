# ci-workflows Specification

## Purpose
TBD - created by archiving change ci-runs-without-warnings. Update Purpose after archive.

## Requirements

### Requirement: Every action runs on Node 24 at an exact release

Every action used by a workflow file of the kit SHALL be referenced as `owner/name@vX.Y.Z` or `owner/name@<full commit SHA>`, at a major that runs on Node
24, and SHALL be listed in a table that records the first such major. A floating major, a branch, `latest` and an expression SHALL NOT be used. The
workflows SHALL give no Node 20 deprecation annotation and no `DEP0040` line from their actions.

#### Scenario: An action below its Node 24 release

- **GIVEN** a workflow that uses `actions/checkout@v4`
- **WHEN** the guard test runs
- **THEN** it fails naming the file, the job and the step, and says the first major that runs on Node 24

#### Scenario: An action the table does not list

- **GIVEN** a workflow that uses an action not in the table
- **WHEN** the guard test runs
- **THEN** it fails with a message to add the action to the table with its first Node 24 major

#### Scenario: A floating reference

- **GIVEN** a workflow that uses `astral-sh/setup-uv@v10`, `@main` or `@latest`, or a reference written as an expression
- **WHEN** the guard test runs
- **THEN** it fails naming the reference

#### Scenario: References that are allowed

- **GIVEN** a reference by full commit SHA, a local `./` action and a `docker://` reference
- **WHEN** the guard test runs
- **THEN** none of them fails

#### Scenario: The workflow as shipped

- **WHEN** the guard test reads the workflows of the repository
- **THEN** every action is at an exact release at or above its table entry and the test passes

### Requirement: The runner is pinned

Every job of a workflow file of the kit SHALL name its runner by a fixed label, `ubuntu-24.04`, and SHALL NOT use a label ending in `-latest`, so that a
change of operating system is made on purpose and not by the label moving.

#### Scenario: A floating runner

- **GIVEN** a job with `runs-on: ubuntu-latest`, or a list or matrix value that ends in `-latest`
- **WHEN** the guard test runs
- **THEN** it fails naming the job

#### Scenario: The jobs as shipped

- **WHEN** the guard test reads the workflows of the repository
- **THEN** the `pre-commit`, `test` and `integration` jobs run on `ubuntu-24.04`

### Requirement: The workflow policy is written where the guard points

The repository's `AGENTS.md` SHALL have a "CI workflows" section that states the action version rule, the runner pin and how to bump either, and the
guard test's failure message SHALL name that section.

#### Scenario: The section exists

- **WHEN** `AGENTS.md` is read
- **THEN** it has the heading "CI workflows", names the guard's table, the exact-tag rule and the runner pin

#### Scenario: The guard names it

- **WHEN** the guard test fails
- **THEN** its message ends with "see AGENTS.md, CI workflows"

### Requirement: A pydantic serializer warning from the checkpoint tests fails the suite

The state a checkpoint test builds from what the graph's nodes wrote SHALL be built through validation, so that a field declared as a tuple holds a
tuple, and a test SHALL fail if serialising that state raises `PydanticSerializationUnexpectedValue`. The pytest options SHALL turn the pydantic
serializer warning into a failure, scoped by its message so that other warnings are only reported.

#### Scenario: A state built from node updates

- **GIVEN** the updates a held unit's nodes wrote, which hold lists for the tuple fields
- **WHEN** the test builds its state and serialises it
- **THEN** no `PydanticSerializationUnexpectedValue` is raised

#### Scenario: A list in a tuple field is seen

- **GIVEN** a state copied with a list in a field declared as a tuple, without validation
- **WHEN** it is serialised
- **THEN** the warning is raised, and the test that holds it fails under the pytest options

#### Scenario: A blocked type is still caught

- **GIVEN** a node update that holds an enum the checkpoint's allowed list refuses
- **WHEN** the rebuilt state is checked
- **THEN** the blocked type is reported as before

#### Scenario: Other warnings are unchanged

- **GIVEN** a test that raises a `UserWarning` of any other message
- **WHEN** it runs
- **THEN** it is reported in the warnings summary and is not failed by the filter
