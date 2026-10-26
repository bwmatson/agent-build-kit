## ADDED Requirements

### Requirement: A join is judged and applied on the direct dependencies

A join SHALL be judged on the stored direct dependencies: a unit taken in SHALL be in a line with the unit it joins when the joined unit is one of its
direct dependencies, and a unit that waits on another unfinished unit besides it, or a unit that depends on the joined unit besides the one taken,
SHALL refuse the join as before. Because a unit no longer stores a dependency that another reaches, a unit that waited on the joined unit only through
the one taken in SHALL NOT refuse the join, and a unit built on the joined unit through a chain SHALL be repointed through the unit it depends on. When
the join is applied the dependents of the unit taken in SHALL be repointed to the unit joined onto, de-duplicated and stored reduced, and a repointed
list SHALL NOT keep a dependency another of its dependencies reaches.

#### Scenario: A grandchild no longer blocks the join

- **GIVEN** units A, B and C in a line, C depending on B alone, and a join of B onto A
- **WHEN** the join is checked
- **THEN** it is permitted, where C's own redundant dependency on A would have refused it as a second dependent

#### Scenario: A second dependent still refuses

- **GIVEN** A with two dependents, B and another unit that does not depend on B
- **WHEN** B is joined onto A
- **THEN** the join is refused naming the other unit, as before

#### Scenario: A join repoints and de-duplicates

- **GIVEN** a unit taken in that has a dependent also listing the unit joined onto
- **WHEN** the join is applied
- **THEN** the dependent lists the unit joined onto once, and a dependency its other dependencies reach is not stored

#### Scenario: A unit that waits on another unfinished unit

- **GIVEN** a unit taken in that also depends on an unfinished unit other than the one joined onto
- **WHEN** the join is checked
- **THEN** it is refused naming that unit, as before

#### Scenario: Not a line

- **GIVEN** a unit that does not depend on the unit it is joined onto directly
- **WHEN** the join is checked
- **THEN** it is refused as not in a line
