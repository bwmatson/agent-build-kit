# review-always-on Specification

## Purpose
TBD - created by archiving change review-by-tier-is-always-on. Update Purpose after archive.

## Requirements

### Requirement: Review by tier is always on and `review.enabled` is ignored with a notice

abk SHALL NOT have a setting that turns review by tier off. A configuration that sets `review.enabled` SHALL load, SHALL ignore the
key whatever its value, and SHALL give one notice naming it, from `abk config` and `abk doctor` and at load, saying it is no longer
used. `abk config` SHALL NOT print it and `abk init` SHALL NOT write it. The planner SHALL estimate a review tier for every unit, the
review prompt SHALL ask for the classification, and a verdict SHALL be computed and recorded for every approved unit, in every
configuration.

#### Scenario: A file that still sets it to false

- **GIVEN** an `abk.yaml` with `review.enabled: false`
- **WHEN** it is loaded and a unit is planned and approved
- **THEN** the key is ignored with one notice, the planner's prompt asks for a tier, and a verdict is recorded

#### Scenario: A file that does not set it

- **WHEN** a configuration with no `review.enabled` is loaded
- **THEN** no notice is given and the behaviour is the same

#### Scenario: What is printed

- **WHEN** `abk config` prints a configuration
- **THEN** no `enabled` key appears under `review`

### Requirement: `global_limits.max_unit_lines` is no longer accepted

A configuration that sets `global_limits.max_unit_lines`, or the same key under the deprecated root `limits`, SHALL fail to load with
a message that names `review.ceilings.full` and says `abk config --migrate` moves the value. `global_limits.min_unit_lines` SHALL
remain. The ceilings SHALL be `review.ceilings.auto`, `light` and `full`, each greater than `min_unit_lines` and in that
descending order, and every check of a unit's size, in planning, in the prompt and in the oversize log, SHALL use the ceiling for the
unit's review tier.

#### Scenario: The old key

- **GIVEN** an `abk.yaml` with `global_limits.max_unit_lines: 900`
- **WHEN** it is loaded
- **THEN** loading fails with a message naming `review.ceilings.full`

#### Scenario: The migration

- **WHEN** `abk config --migrate` runs over that file
- **THEN** `review.ceilings.full` is 900, the old key is gone, and every other line is as it was

#### Scenario: The floor stays

- **GIVEN** `min_unit_lines: 400` and `review.ceilings.full: 300`
- **WHEN** the file is loaded
- **THEN** loading fails saying a ceiling must exceed `min_unit_lines`

#### Scenario: Sizing by tier

- **GIVEN** a unit expected `light` with an estimate of 1500 lines
- **WHEN** the planner checks its size
- **THEN** the unit is within the `light` ceiling and is not refused
