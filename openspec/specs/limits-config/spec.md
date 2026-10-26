# limits-config Specification

## Purpose
TBD - created by archiving change limits-split-into-global-and-project. Update Purpose after archive.

## Requirements

### Requirement: The workspace-wide limits are `global_limits`

The settings that bound the workspace as a whole (sizes, depth caps, rounds, timeouts and the other settings of the block
the workspace has so far called `limits`) SHALL be configured under the root key `global_limits`, with the same names, types,
defaults and validation they had, except for the three scheduling settings the next requirements move. The usage-window
thresholds of a runtime (`runtimes.<name>.limits`) SHALL be a different block and SHALL keep their name. The configuration
loaded in memory SHALL expose the block as `global_limits`, and `abk config` SHALL print it under that name.

#### Scenario: A setting under its new name

- **GIVEN** an abk.yaml with `global_limits: {max_review_rounds: 5}`
- **WHEN** it is loaded
- **THEN** the review round bound is 5 and every other setting of the block has its default

#### Scenario: The runtime's windows keep their name

- **GIVEN** an abk.yaml with `runtimes.claude_code.limits` set
- **WHEN** it is loaded
- **THEN** the usage thresholds are read from there, and no deprecation is reported

#### Scenario: The effective config prints the new name

- **WHEN** `abk config` prints the effective configuration
- **THEN** the block is printed as `global_limits`, with `project_limits` beside it, and no `limits` key at the root

### Requirement: `limits` is accepted as a deprecated alias

A root key `limits` SHALL load as `global_limits`, with the same content and the same validation. `abk config` and `abk doctor`
SHALL each say that `limits` is deprecated and name `abk config --migrate` as the way to move to the new names, and SHALL
still load and run. A file with both `limits` and `global_limits` SHALL be an error that names both keys and writes nothing.
The error messages for a setting under the alias SHALL name the key as the file spells it.

#### Scenario: The old key alone

- **GIVEN** an abk.yaml with `limits: {max_review_rounds: 5}` and no `global_limits`
- **WHEN** it is loaded
- **THEN** the review round bound is 5 and loading succeeds

#### Scenario: A warning from `abk config`

- **WHEN** `abk config` runs against a file that uses `limits`
- **THEN** it prints the effective configuration, says on the error stream that `limits` is deprecated for `global_limits` and that `abk config --migrate` moves it, and exits 0

#### Scenario: A warning from `abk doctor`

- **WHEN** `abk doctor` runs against a file that uses `limits`
- **THEN** it reports a warning for the configuration naming the deprecated key and the command, and no failure

#### Scenario: No warning for the new key

- **WHEN** `abk config` or `abk doctor` runs against a file that uses only `global_limits`
- **THEN** neither says anything about deprecation

#### Scenario: Both keys

- **GIVEN** an abk.yaml with both `limits` and `global_limits`
- **WHEN** it is loaded
- **THEN** loading fails with an error naming both keys and saying to keep one, and nothing is written

### Requirement: `project_limits` holds the settings counted for each project

The root key `project_limits` SHALL hold `max_units_in_progress` (a whole number of at least 1, default 5),
`max_concurrent_stacks` (default 4) and `max_concurrent_restacks` (a whole number of at least 1, default 2), each a limit of one
project, applied to every project separately. It SHALL be configured once, at the root: no repo and no project SHALL override
it. A key it does not know, a value of the wrong type and a value under its minimum SHALL fail the load naming the setting, as
every setting does. `abk config` SHALL print both blocks.

#### Scenario: The defaults

- **GIVEN** an abk.yaml with no `project_limits`
- **WHEN** it is loaded
- **THEN** the units in progress limit is 5, the build workers are 4 and the restack workers are 2

#### Scenario: Set once at the root

- **GIVEN** `project_limits: {max_units_in_progress: 3}`
- **WHEN** it is loaded
- **THEN** every project's limit on units in progress is 3

#### Scenario: A value under its minimum

- **WHEN** `project_limits.max_units_in_progress` or `max_concurrent_restacks` is 0, negative, a float or a string
- **THEN** loading fails naming the setting

#### Scenario: No override per repo

- **WHEN** a repo's entry holds a `project_limits` or `limits` key
- **THEN** loading fails as it does for any key the schema does not know

#### Scenario: Both blocks are shown

- **WHEN** `abk config` prints the effective configuration
- **THEN** `global_limits` and `project_limits` both appear, each with its defaults filled in

### Requirement: A scheduling setting left in `global_limits` is refused with a pointer

`max_units_in_progress`, `max_concurrent_stacks` and `max_concurrent_restacks` SHALL NOT be accepted under `global_limits`, nor
under `limits` used as its alias. A file that holds one SHALL fail to load with an error that names the key as the file spells
it, says the setting is now counted for each project and belongs under `project_limits`, and names `abk config --migrate`.
`abk config --migrate` and `abk config --path` SHALL still run against such a file. No other setting SHALL move.

#### Scenario: A moved setting under the new block

- **GIVEN** `global_limits: {max_units_in_progress: 5}`
- **WHEN** the file is loaded
- **THEN** loading fails with `global_limits.max_units_in_progress`, the pointer to `project_limits.max_units_in_progress` and the migrate command

#### Scenario: A moved setting under the old key

- **GIVEN** `limits: {max_concurrent_stacks: 4}`
- **WHEN** the file is loaded
- **THEN** loading fails naming `limits.max_concurrent_stacks`, with the same pointer

#### Scenario: Only those three move

- **GIVEN** `global_limits` holding `max_review_rounds`, `max_unit_lines` and `stack_depth_build_cap`
- **WHEN** the file is loaded
- **THEN** it loads, and each setting is read from `global_limits`

#### Scenario: The commands that repair it still run

- **GIVEN** a file that fails to load for a moved setting
- **WHEN** `abk config --migrate` or `abk config --path` runs
- **THEN** it does not stop on the load failure

#### Scenario: A new file is written with the new names

- **WHEN** `abk init` writes the generated-file patterns it detects into an abk.yaml
- **THEN** they are written under `global_limits`, and an existing file's `limits` key is extended in place when it has one and `global_limits` does not
