## ADDED Requirements

### Requirement: A unit parked on a tier 2 split holds no place, planned or unplanned, whatever its cause field says

A unit in state `planned` or `unplanned` whose `parked_splits` is non-empty (it was parked on a held tier 2 split and has not run its e2e step since)
SHALL NOT count as in progress, whatever work it has (a branch, a pushed commit or a pull request), because it has nothing to run until the split is
released. The rule SHALL NOT depend on the unit's `cause`, which is read from its latest history entry and is lost by a state change that records no
cause: it SHALL hold whether the cause is `split_held` or empty. It SHALL NOT hold when the latest cause is another one (for example `requeued`,
`host_unavailable` or `service_unavailable`), because the unit was then released or interrupted after the park and is on its way to run. A `planned`
unit with the cause `split_held` SHALL still not count, whether or not its `parked_splits` is set. The unit SHALL NOT draw on the room under
`max_units_in_progress`, and `abk status` SHALL leave it out of the count of units in progress and of the line that says the queue is full, and
SHALL list it, planned or unplanned, as parked on its split. A unit whose `parked_splits` has been cleared (a run that resumed it has run its e2e
step), an `unplanned` unit with no parked splits that has a pull request, a branch or a pushed commit, and any unit in state `running` or `in_review`,
SHALL count by the normal rules. When the split is released an `unplanned` unit parked on it SHALL NOT be resumed, requeued or started, because the
plan no longer has it; it SHALL stay uncounted until the plan carries it again as a `planned` unit, and its branch and worktree SHALL be kept.

#### Scenario: A planned unit parked on a split with an empty cause is not counted

- **GIVEN** a `planned` unit with a branch, no pull request, `parked_splits` `["acp"]` and a latest history entry that has no cause
- **WHEN** the count of units in progress is worked out
- **THEN** it is not counted

#### Scenario: An unplanned unit parked on a split with an empty cause is not counted

- **GIVEN** an `unplanned` unit with a branch, no pull request, `parked_splits` `["acp"]` and a latest history entry that has no cause
- **WHEN** the count of units in progress and the room to start are worked out
- **THEN** it is not counted

#### Scenario: Two parked units leave the room whole

- **GIVEN** a limit of 5, four counted units, a planned unit parked on `acp` with an empty cause and an unplanned unit parked on `acp` with an empty cause
- **WHEN** the count of units in progress and the room to start are worked out
- **THEN** the count is 4 and the room is 1

#### Scenario: The status leaves them out and lists them

- **GIVEN** the same units, a ready unit and the split `acp` held
- **WHEN** `abk status` runs
- **THEN** the queue-full line does not appear, the count of units in progress is 4, and both parked units are listed as parked on `acp`

#### Scenario: A planned unit with the cause split_held is as before

- **GIVEN** a `planned` unit with a branch and the cause `split_held`
- **WHEN** the count is worked out
- **THEN** it is not counted

#### Scenario: A unit whose parked splits were cleared counts again

- **GIVEN** a unit that was parked on `acp`, resumed, and whose e2e step ran so that its `parked_splits` is empty, and that has a branch and is not blocked
- **WHEN** the count is worked out
- **THEN** it counts by the normal rules

#### Scenario: A parked unit released and requeued counts when it runs

- **GIVEN** a `planned` unit with `parked_splits` `["acp"]` whose latest cause is `requeued`
- **WHEN** the count is worked out
- **THEN** it counts by the normal rules, because it is no longer waiting for the split

#### Scenario: An unplanned unit with a pull request still counts

- **GIVEN** an `unplanned` unit with a pull request and no parked splits
- **WHEN** the count is worked out
- **THEN** it counts, as before this change

#### Scenario: An unplanned unit with pushed work and no park still counts

- **GIVEN** an `unplanned` unit with a pushed commit, no pull request and no parked splits
- **WHEN** the count is worked out
- **THEN** it counts, as before this change

#### Scenario: Release does not restart it

- **GIVEN** an `unplanned` unit parked on `acp` and `acp` released
- **WHEN** a round runs
- **THEN** the unit is not resumed or started, it stays uncounted, its branch and worktree are kept, and `abk status` still lists it as unplanned and parked on `acp`

#### Scenario: It counts again only when the plan carries it

- **GIVEN** an `unplanned` unit parked on `acp`, `acp` released, and a replan that plans it again
- **WHEN** the unit is planned
- **THEN** the rules for a planned unit apply to it: the round starts it, resuming only its parked split, and it counts once it is running

### Requirement: A replan keeps the splits a unit is parked on

`UnitStore.upsert` SHALL carry `parked_splits`, `parked_sha`, `parked_snapshot` and `parked_attempts` over from the existing record of a unit, as it
does its branch, pull request and feedback, so that a replan that includes the unit, one that leaves it out and sets it `unplanned`, and one that
plans an `unplanned` unit again each leave what it is parked on as it was. A unit parked on a held split SHALL NOT be released by a replan.

#### Scenario: A replan keeps a parked planned unit's splits

- **GIVEN** a `planned` unit parked on `acp` with a `parked_sha`, a `parked_snapshot` and a `parked_attempts` of 1, and a plan that includes it
- **WHEN** the plan is merged into the store
- **THEN** the unit's `parked_splits`, `parked_sha`, `parked_snapshot` and `parked_attempts` are as they were

#### Scenario: A demotion to unplanned keeps them

- **GIVEN** a `planned` unit parked on `acp` and a plan of its change that leaves it out
- **WHEN** the plan is merged into the store
- **THEN** the unit is `unplanned` and its parked fields are as they were

#### Scenario: A unit planned again keeps them

- **GIVEN** an `unplanned` unit parked on `acp` and a plan that includes it
- **WHEN** the plan is merged into the store
- **THEN** the unit is `planned` and its parked fields are as they were

#### Scenario: A replan does not release a held split's unit

- **GIVEN** a `planned` unit with the cause `split_held` parked on `acp`, `acp` held, and a plan that includes the unit
- **WHEN** the plan is merged into the store and the release step runs
- **THEN** the unit is not resumed
