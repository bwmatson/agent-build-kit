## MODIFIED Requirements

### Requirement: The planner joins small related sequential work

When a change is planned, the planner SHALL consider every unit that has not
started — those of the change being planned and those already planned, of any
change — and SHALL be able to join two of them into one: a new change's task
groups onto an existing unit, or one existing unit onto another. A join SHALL
be accepted only when all of the following hold: the two are in the same repo,
tier and e2e-test split; the later depends on the earlier, or would, nothing else depends on
the earlier, and the later waits on nothing else unfinished; neither has
started; none of the groups involved is tagged `[e2e-test]` (flagged or not), or flagged as
acceptance, contract or narrowing; none is marked to be kept separate; and the combined estimate is at
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

#### Scenario: A different e2e-test split

- **WHEN** the groups and the unit are in different e2e-test splits (the `Split:` line of the group, `rest`
  when it has none)
- **THEN** the join is refused

#### Scenario: A different project

- **WHEN** the groups and the unit are in one repo and tier but are tagged for different projects
- **THEN** the join is refused

#### Scenario: A plain e2e-test group

- **WHEN** a join would carry a group tagged `[e2e-test]` with no flag, onto a unit or another group that is also `[e2e-test]` of the same repo,
  project and split
- **THEN** the join is refused, saying an `[e2e-test]` group always has a unit of its own

#### Scenario: Two unstarted e2e-test units in a line

- **WHEN** one unstarted unit of an `[e2e-test]` group depends on another and nothing else depends on it, under the ceiling
- **THEN** the join is refused

## ADDED Requirements

### Requirement: An e2e-test group is a unit of its own

A task group tagged `[e2e-test]`, whether or not it carries a flag, SHALL be built by a unit that holds that group and no other, and SHALL NOT be
carried by another unit. This SHALL be enforced on every plan: a plan that gives one unit an `[e2e-test]` group together with any other group of
the same change, or a join that carries an `[e2e-test]` group or joins a unit holding one, SHALL be refused and re-asked within the attempt budget.
The group SHALL need no `Separate:` line; a `Separate:` line on an `[e2e-test]` group SHALL be accepted and `abk tags` SHALL say it is redundant.
The unit's dependencies are those the chain gives any group. The planner prompt SHALL say all of this in the places that state the grouping and the
join rules.

#### Scenario: Consecutive small e2e-test groups

- **GIVEN** a change whose groups 4 and 5 are small, `[app] [e2e-test]` with no flag and the same split
- **WHEN** a plan puts both in one unit
- **THEN** the plan is refused naming the unit and both groups, and the planner is asked again

#### Scenario: One unit per group

- **WHEN** the same change is planned and the planner returns a unit for each of groups 4 and 5
- **THEN** the plan is accepted, group 5's unit depends on group 4's as the chain gives, and each unit's id is `<change>/<its group>`

#### Scenario: A stored unit that already holds several e2e-test groups

- **GIVEN** an unstarted stored unit carrying `[e2e-test]` groups 1, 2 and 3 of one change
- **WHEN** the change is planned again
- **THEN** the new plan is checked as any plan, so it gives each group a unit of its own, and nothing else rewrites the stored unit

#### Scenario: A started unit keeps its groups

- **GIVEN** a started unit (a branch, a pushed commit, a pull request or an approval) carrying several `[e2e-test]` groups
- **WHEN** the change is planned again
- **THEN** it keeps its groups as the merged rule "a started unit keeps its groups" says, and is not split

#### Scenario: A Separate line is redundant

- **WHEN** `abk tags` reads an `[e2e-test]` group with a `Separate: reason` line
- **THEN** it prints a warning, not an error, that the line is redundant because the group is never joined
