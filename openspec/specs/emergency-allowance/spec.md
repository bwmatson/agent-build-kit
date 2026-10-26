# emergency-allowance Specification

## Purpose
TBD - created by archiving change priority-0-units-may-use-an-extra-allowance. Update Purpose after archive.

## Requirements

### Requirement: The emergency lane cap is a project limit

The `project_limits` block SHALL hold `emergency_extra`, an integer of 0 or more that defaults to 1, the cap on how many priority-0 units may be started past the normal limits at once
in a project (the emergency lane cap, as `max_concurrent_restacks` is the restack lane's), applied to each project as the other scheduling limits are. It SHALL NOT be a margin shared with
the restack lane. A value that is
below 0 or not an integer SHALL be refused when the configuration is loaded, naming `project_limits.emergency_extra`. A misspelled key SHALL be refused as any unknown key is. The key
SHALL NOT be accepted in `global_limits` or in the deprecated `limits` block, where the error SHALL name the block and say the setting belongs in `project_limits`, and SHALL NOT say
`abk config --migrate` moves it. `abk config --migrate` SHALL NOT add, move, rewrite or remove the key: a file that holds it keeps its line unchanged. `abk doctor` SHALL report
an invalid value as it reports any invalid configuration, and SHALL add no check for a valid one. A configuration without the key SHALL read as 1.

#### Scenario: The default

- **GIVEN** an `abk.yaml` with a `project_limits` block that does not name `emergency_extra`
- **WHEN** the configuration is loaded
- **THEN** the setting reads 1

#### Scenario: Zero turns it off

- **GIVEN** `emergency_extra: 0`
- **WHEN** the configuration is loaded
- **THEN** it is accepted and reads 0, and no unit starts past the normal limits

#### Scenario: A bad value

- **GIVEN** `emergency_extra` of `-1`, `1.5` or `many`
- **WHEN** the configuration is loaded or `abk doctor` runs
- **THEN** the error names `project_limits.emergency_extra`, and `abk doctor` reports it as a configuration failure

#### Scenario: A misspelling

- **GIVEN** a `project_limits` key `emergency_extras`
- **WHEN** the configuration is loaded
- **THEN** it is refused as an unknown key

#### Scenario: The key in the wrong block

- **GIVEN** `emergency_extra` under `global_limits` or under `limits`
- **WHEN** the configuration is loaded
- **THEN** the error names that block and `project_limits`, and does not say `abk config --migrate` moves it

#### Scenario: The migration leaves the key alone

- **GIVEN** an `abk.yaml` with the scheduling settings under `limits` and `emergency_extra: 2` under `project_limits`
- **WHEN** `abk config --migrate` writes the file
- **THEN** the three old settings move as before and the `emergency_extra` line is unchanged; a file with no old settings and the key reports nothing to migrate

#### Scenario: Each project has its own lane cap

- **GIVEN** two projects and `emergency_extra: 1`
- **WHEN** the lane use is worked out
- **THEN** each project has its own cap and its own use, and no total is kept
