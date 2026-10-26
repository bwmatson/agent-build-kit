# Spec Delta

## Purpose

Defines the upper bound on how much work the planner may put in one unit: where
it is configured and how planning respects it. Nothing here constrains a branch
after it is built.

## ADDED Requirements

### Requirement: A workspace configures a ceiling on a unit's size

The workspace SHALL configure the largest number of changed lines one unit may
carry, defaulting to 1000, and that ceiling SHALL be required to exceed the
existing floor on unit size. A configuration whose floor is at or above its
ceiling SHALL fail to load, naming both values.

#### Scenario: The default

- **WHEN** a workspace configures no ceiling
- **THEN** the ceiling is 1000 changed lines

#### Scenario: A floor above the ceiling

- **WHEN** a workspace sets a floor at or above the ceiling
- **THEN** loading the configuration fails, naming both values, rather than
  producing plans that cannot satisfy either

### Requirement: Planning keeps units under the ceiling

The planner SHALL be told the ceiling, task groups SHALL NOT be combined into a
unit whose estimate exceeds it, and a plan that returns such a unit SHALL be
rejected with that reason and re-asked within the existing attempt budget.

#### Scenario: Grouping small task groups

- **WHEN** consecutive same-repo groups would together exceed the ceiling
- **THEN** they are split across units, even where the floor would have kept
  grouping them

#### Scenario: A plan that ignores the ceiling

- **WHEN** a returned plan contains a unit estimated over the ceiling
- **THEN** the plan is rejected with that reason and the planner is asked again

### Requirement: A task group too large to plan is reported, not planned badly

When one task group's own estimate exceeds the ceiling, no grouping can satisfy
it, so the pipeline SHALL report that the change's tasks need splitting and leave
the change unplanned, rather than spending planning attempts or emitting a unit
over the ceiling.

#### Scenario: One oversized group

- **WHEN** a change contains a single task group estimated over the ceiling
- **THEN** the change is left unplanned with a message naming that group and
  saying its tasks must be split
