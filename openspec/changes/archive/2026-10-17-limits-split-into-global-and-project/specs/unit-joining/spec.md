## MODIFIED Requirements

### Requirement: The planner joins small related sequential work

When a change is planned, the planner SHALL consider every unit that has not
started — those of the change being planned and those already planned, of any
change — and SHALL be able to join two of them into one: a new change's task
groups onto an existing unit, or one existing unit onto another. A join SHALL
be accepted only when all of the following hold: the two are in the same repo,
the same project and the same tier; the later depends on the earlier, or would, nothing else depends on
the earlier, and the later waits on nothing else unfinished; neither has
started; none of the groups involved is flagged as acceptance, contract or
narrowing; none is marked to be kept separate; and the combined estimate is at
or under the unit size ceiling. A join that fails any of these SHALL be
refused, not repaired. Joins SHALL be found in the planning pass itself, with
no further agent call.

#### Scenario: Two units already planned

- **WHEN** a new change is planned while two unstarted units of other changes
  sit in a straight line in the same repo and tier, related and together under
  the ceiling
- **THEN** the later unit's groups are carried by the earlier and the later
  unit no longer exists

#### Scenario: Three in a line

- **WHEN** three unstarted units in a straight line are together under the
  ceiling
- **THEN** one planning pass may leave a single unit carrying all three

#### Scenario: Two small related changes in a line

- **WHEN** a new change's only group would depend on an unstarted unit in the
  same repo and tier, nothing else depends on that unit, and together they are
  under the ceiling
- **THEN** the group is carried by that unit and no new unit is created

#### Scenario: Something else depends on the earlier unit

- **WHEN** another unit already depends on the unit a join names
- **THEN** the join is refused

#### Scenario: Together they are over the ceiling

- **WHEN** the combined estimate is over the unit size ceiling
- **THEN** the join is refused

#### Scenario: A different repo or tier

- **WHEN** the groups and the unit differ in repo or in tier
- **THEN** the join is refused

#### Scenario: A different project

- **WHEN** the groups and the unit are in one repo and tier but are tagged for different projects
- **THEN** the join is refused
