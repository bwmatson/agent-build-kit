## MODIFIED Requirements

### Requirement: A workspace configures a ceiling on a unit's size

The workspace SHALL configure the largest number of changed lines one unit may
carry. Before per-tier sizing is on (`review.enabled` false) that is
`global_limits.max_unit_lines`, defaulting to 750, for every unit, and it SHALL
be the same as `review.ceilings.full` when both are set. With `review.enabled` true it is the ceiling of
the review tier the unit is expected to get (see review-tier-ceilings), and the
`full` ceiling is the one 750 stands for. The ceiling in effect for a unit SHALL be required to exceed the
floor on unit size, which defaults to 400. A workspace that sets either value
keeps it. A configuration whose floor is at or above a ceiling in effect SHALL fail to
load, naming both values.

#### Scenario: The default

- **WHEN** a workspace configures no ceiling
- **THEN** the ceiling is 750 changed lines and the floor is 400

#### Scenario: A floor above the ceiling

- **WHEN** a workspace sets a floor at or above the ceiling
- **THEN** loading the configuration fails, naming both values, rather than
  producing plans that cannot satisfy either

#### Scenario: Per-tier sizing is on

- **GIVEN** `review.enabled` is true and the default ceilings
- **WHEN** a unit expected to get `auto` review is planned
- **THEN** its ceiling is 5000 changed lines, and the floor is still 400
