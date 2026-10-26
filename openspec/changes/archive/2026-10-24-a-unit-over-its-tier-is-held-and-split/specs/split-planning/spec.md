## ADDED Requirements

### Requirement: The planner is given pins when it re-plans a held unit

A plan of a held unit's groups SHALL be asked with the unit's groups in order, the tier it earned, the tier it was planned for and the
groups to pin, and SHALL be told to put the pinned groups in a unit of their own at the earned tier within that tier's ceiling, to keep the
rest together at the planned tier within its larger ceiling, to keep the groups in their order, and to chain the resulting units by
dependency. With no pinned groups it SHALL be told every piece takes the earned tier and is to be brought under its ceiling. `tasks.md`
SHALL NOT be changed. Only the held unit's groups SHALL be planned, every other group of the change being as built.

#### Scenario: A driver in the middle

- **GIVEN** a unit of groups 1 to 5 with group 3 the driver
- **WHEN** the planner is asked
- **THEN** its instructions name the groups in order, pin group 3 at the earned tier, and say the rest stay at the planned tier

#### Scenario: No drivers

- **GIVEN** a unit over its ceiling with no driver
- **WHEN** the planner is asked
- **THEN** the instructions give the ceiling and ask only that each unit be brought under it

### Requirement: A plan that ignores the pins is refused

The plan check SHALL refuse a plan in which a driver group shares a unit with a group that is not a driver, in which a unit of driver
groups is not at the earned tier or a unit of others is not at the planned tier, in which the units are not an ordered partition of the
held unit's groups into contiguous runs, in which a unit's id is not its parent's with `-s<k>` in order, in which the first unit does not
depend on what the held unit depended on or a later unit does not depend on the one before it, or in which a unit depends on another unit
of the change. The ceiling, flag, dependency and acceptance checks SHALL apply as to any plan, at each unit's tier and to the plain
ceilings. Each refusal SHALL name the unit and the rule.

#### Scenario: A driver beside another group

- **WHEN** a plan puts the driver group 3 and group 2 in one unit
- **THEN** the plan is refused naming the unit and both groups

#### Scenario: A wrong tier

- **WHEN** the unit of the driver group is planned at the tier the unit was planned for
- **THEN** the plan is refused naming the unit and the earned tier

#### Scenario: Out of order

- **WHEN** a plan puts group 4 in a unit before the unit of group 3
- **THEN** the plan is refused naming the order

#### Scenario: A correct split

- **GIVEN** a unit of groups 1 to 5 with group 3 the driver
- **WHEN** the plan is units for groups 1 and 2, for 3, and for 4 and 5, chained in order, at the planned, earned and planned tiers
- **THEN** the plan is accepted

#### Scenario: Several drivers in a row

- **GIVEN** drivers 2 and 3, adjacent
- **WHEN** a plan puts them in one unit of their own within the earned ceiling
- **THEN** the plan is accepted

### Requirement: A later plan of the change keeps the pins

A plan of a change SHALL be given the pins of its superseded units whose pieces have not all started, and SHALL be refused if it ignores
them, so that an ordinary re-plan does not undo a split.

#### Scenario: A change edited after a split

- **GIVEN** a change whose superseded unit's pieces are unstarted
- **WHEN** its `tasks.md` is edited and the change is planned again
- **THEN** the planner is told to keep the driver group alone and the plan is refused if it does not

### Requirement: Each split is bounded, counted per lineage and recorded

The pipeline SHALL keep, on a held unit and on each piece, the number of split rounds its lineage has used, SHALL add one to it for each
attempt that succeeds or fails, and SHALL NOT add one for an outage. A piece SHALL inherit its parent's count. An attempt SHALL be made
only when the count is below `review.split_rounds`.

#### Scenario: A piece split again

- **GIVEN** a unit split once, and a piece of it that is held by size
- **WHEN** it is split
- **THEN** it has one round left in `split_rounds: 2`, and a piece of that split has none

#### Scenario: Zero rounds

- **GIVEN** `split_rounds: 0`
- **WHEN** a unit is held by size
- **THEN** no planner call is made and it is held for a person

### Requirement: Built work is reused when the old branch was built per group and rebuilt otherwise

A piece SHALL take the commit pairs of its groups from the superseded unit's branch, in order, by cherry-pick onto its own branch when its
run is prepared, when that branch's commits are exactly a `test:` and `feat:` pair for each of the unit's groups, in order; the run SHALL
then go on from the branch as a partly built unit does. A branch with any other commit on it SHALL NOT be reused, and a pair that does not
apply cleanly SHALL end the reuse at that group, the rest of the piece being built as any unit is. The superseded branch SHALL be kept under
its ref either way.

#### Scenario: A branch built per group

- **GIVEN** a superseded unit whose branch holds three pairs and a piece for the third group
- **WHEN** the piece is prepared
- **THEN** the third pair is on the piece's branch, and no agent writes that group

#### Scenario: A rework commit

- **GIVEN** a superseded branch with a `fix:` commit after its pairs
- **WHEN** a piece is prepared
- **THEN** nothing is cherry-picked and the piece is built from scratch

#### Scenario: A pair that conflicts

- **GIVEN** a piece for groups 2 and 3 whose first pair applies and whose second does not
- **WHEN** it is prepared
- **THEN** group 2's pair is on the branch and group 3 is built by the agent
