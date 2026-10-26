# review-tier-estimate Specification

## Purpose
TBD - created by archiving change review-policy-and-verdict-recorded-in-shadow. Update Purpose after archive.

## Requirements

### Requirement: The planner estimates the review tier of each unit

When review is enabled, the planner SHALL return for each unit an expected review tier, `auto`, `light` or `full`, and the tier SHALL
be recorded on the unit. The tier SHALL be at least the floor the tags and the task text give: `full` for a unit that builds a group
flagged `contract`, `narrow` or `acceptance`, and `full` for a unit that builds a group whose task text names a path the protected set
matches. A unit's floor SHALL be the highest floor of the groups it builds. A reply below the floor, or a value that is not one of
the three, SHALL be refused naming the unit, the group and the floor, and a reply that omits the value SHALL take the floor. The
estimate SHALL size nothing and change no plan.

#### Scenario: A contract group

- **GIVEN** a change with a group flagged `[contract]`
- **WHEN** it is planned and the planner returns `auto` for the unit that builds it
- **THEN** the reply is refused naming the unit, the group and the floor `full`

#### Scenario: A protected path in the task text

- **GIVEN** a group whose task names `db/migrations/0042_add_index.sql`
- **WHEN** it is planned
- **THEN** its unit's floor is `full`

#### Scenario: The planner raises it

- **GIVEN** a group with no flag and no protected path
- **WHEN** the planner returns `light`
- **THEN** the unit is recorded with `light`

#### Scenario: Omitted

- **WHEN** the planner's reply gives a unit no review tier
- **THEN** the unit takes its floor

### Requirement: A started unit keeps its recorded estimate

A re-plan SHALL leave the review tier recorded on a unit that has started, and a unit planned before review tiers existed SHALL have
none recorded.

#### Scenario: A re-plan

- **GIVEN** a started unit with the estimate `light`
- **WHEN** its change is planned again
- **THEN** the unit still reads `light`

### Requirement: The estimate is compared with the verdict

For every unit with a recorded estimate and a verdict, abk SHALL record whether the estimate was below, equal to or above the
verdict's evidence tier, as a metric by repo and class.

#### Scenario: Below

- **GIVEN** a unit estimated `auto` whose evidence tier is `full`
- **WHEN** its verdict is recorded
- **THEN** the planner-accuracy metric counts one `below`
