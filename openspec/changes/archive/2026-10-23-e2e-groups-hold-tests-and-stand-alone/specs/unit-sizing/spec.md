## ADDED Requirements

### Requirement: An e2e-test group is sized and planned alone

The size rules SHALL treat an `[e2e-test]` group as a unit by itself: the planner SHALL NOT group consecutive `[e2e-test]` groups to reach the
minimum size, the unit's estimate SHALL be that group's, and a single `[e2e-test]` group estimated over the ceiling SHALL be reported as needing
its tasks split, as any single group is. The planner prompt's grouping bullet SHALL say that it does not apply to `[e2e-test]` groups.

#### Scenario: Small consecutive e2e-test groups are not grouped for size

- **GIVEN** two consecutive `[e2e-test]` groups of one repo each estimated at 60 lines, with a minimum of 300
- **WHEN** the change is planned
- **THEN** each is a unit of its own and neither plan nor join groups them to reach the minimum

#### Scenario: One e2e-test group over the ceiling

- **GIVEN** an `[e2e-test]` group whose honest estimate is over the ceiling
- **WHEN** the change is planned
- **THEN** it is reported as needing its tasks split

#### Scenario: Unit-test groups are grouped as before

- **GIVEN** consecutive small `[unit-test]` groups of one repo
- **WHEN** the change is planned
- **THEN** they may be grouped to reach the minimum, as before
