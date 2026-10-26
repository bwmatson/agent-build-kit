## MODIFIED Requirements

### Requirement: Every change a unit carries is built, ticked and archived through it

A unit's build and review SHALL cover every group it carries and name each
change they belong to. When the unit lands, each carried group SHALL be ticked
in its own change's tracking copy of the tasks (the repository's `tasks.md` is written only when the change is archived). A change SHALL be ready to archive when every one of
its groups is in a unit that has landed, whether or not the change has a unit
of its own. A `Needs` line naming a carried group SHALL resolve to the unit
that carries it.

#### Scenario: A change wholly carried by another change's unit

- **WHEN** all of a change's groups are carried by another change's unit and
  that unit merges
- **THEN** the change's tasks are ticked in its tracking copy and it is ready to archive

#### Scenario: Not before

- **WHEN** the unit carrying a change's groups is still in review
- **THEN** that change is not ready to archive

#### Scenario: A dependency on a carried group

- **WHEN** a task group declares it needs a group that another change's unit
  carries
- **THEN** it waits on that unit
