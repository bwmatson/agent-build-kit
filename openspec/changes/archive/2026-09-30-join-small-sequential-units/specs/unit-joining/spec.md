# Spec Delta

## Purpose

Defines when task groups from different changes are built as one unit, and how
such a unit is built, recorded and archived.

## ADDED Requirements

### Requirement: A unit may carry task groups from more than one change

A unit SHALL be able to record task groups taken from changes other than its
own, in order, while keeping the identifier, branch and pull request derived
from its own change. A unit that records none SHALL behave exactly as before.

#### Scenario: A stored unit from before

- **WHEN** a unit recorded without groups from other changes is loaded
- **THEN** it is built, reviewed and archived as it was before this change

### Requirement: Every change a unit carries is built, ticked and archived through it

A unit's build and review SHALL cover every group it carries and name each
change they belong to. When the unit lands, each carried group SHALL be ticked
in its own change's tasks. A change SHALL be ready to archive when every one of
its groups is in a unit that has landed, whether or not the change has a unit
of its own. A `Needs` line naming a carried group SHALL resolve to the unit
that carries it.

#### Scenario: A change wholly carried by another change's unit

- **WHEN** all of a change's groups are carried by another change's unit and
  that unit merges
- **THEN** the change's tasks are ticked and it is ready to archive

#### Scenario: Not before

- **WHEN** the unit carrying a change's groups is still in review
- **THEN** that change is not ready to archive

#### Scenario: A dependency on a carried group

- **WHEN** a task group declares it needs a group that another change's unit
  carries
- **THEN** it waits on that unit

### Requirement: The planner joins small related sequential work

When a change is planned, the planner SHALL consider every unit that has not
started — those of the change being planned and those already planned, of any
change — and SHALL be able to join two of them into one: a new change's task
groups onto an existing unit, or one existing unit onto another. A join SHALL
be accepted only when all of the following hold: the two are in the same repo
and tier; the later depends on the earlier, or would, nothing else depends on
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

### Requirement: A unit joined into another is replaced by it

When one existing unit is joined onto another, the joined unit SHALL be removed
and every unit that depended on it SHALL depend on the unit that carries its
groups. A later planning of its change SHALL NOT create a unit for groups
another unit already carries.

#### Scenario: Something depended on the joined unit

- **WHEN** a unit is joined onto the one before it and a third unit depended
  on it
- **THEN** the third unit depends on the unit that now carries its groups

#### Scenario: Its change is planned again

- **WHEN** the change of a unit that was joined away is planned again with its
  tasks unchanged in those groups
- **THEN** no unit is created for the groups already carried

### Requirement: Only unstarted work is joined

A unit that has a branch, a commit, a pull request or a step to resume at, or
that has finished, SHALL NOT be joined to another unit and SHALL NOT have
anything joined to it. Whether each unit has started SHALL be re-checked at the
moment the plan is written; if either has, that join SHALL be dropped and both
units left untouched, and the rest of the plan SHALL still be written.

#### Scenario: A unit in review

- **WHEN** a join names a unit that is running, in review, merged or otherwise
  finished
- **THEN** the join is refused

#### Scenario: The unit starts while the plan is made

- **WHEN** a unit begins building between the planner proposing a join onto it
  and the plan being written
- **THEN** neither unit is changed, the rest of the plan is written, and a new
  change whose groups were to be carried is planned on a later round

### Requirement: A task group can be kept separate

A task group marked `Separate:` with a reason SHALL NOT be carried by another
change's unit, and no other change's groups SHALL be added to its unit. The
reason SHALL be required.

#### Scenario: A change its author wants reviewed alone

- **WHEN** a change's group is marked separate and is small, related and in
  line with an unstarted unit
- **THEN** it gets a unit of its own

#### Scenario: No reason given

- **WHEN** a group is marked separate with no reason
- **THEN** tag validation rejects it

### Requirement: A join is reported

A join SHALL be logged when planned, naming the groups, the unit and the
combined estimate. The unit graph and the unit's pull request SHALL name every
change the unit carries and which groups.

#### Scenario: Reading the pull request

- **WHEN** a person opens the pull request of a unit carrying two changes
- **THEN** its description lists both changes and the groups from each
