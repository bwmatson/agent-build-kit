# hold-and-split Specification

## Purpose
TBD - created by archiving change a-unit-over-its-tier-is-held-and-split. Update Purpose after archive.

## Requirements

### Requirement: The review section configures a ceiling buffer and a number of split rounds

The `review` section of abk.yaml SHALL accept `ceiling_buffer`, a fraction from 0 to 1 defaulting to 0.2, and `split_rounds`, an integer
from 0 to 2 defaulting to 2. A value outside its range SHALL fail loading naming the key and the value. A configuration in which the
`auto` ceiling in effect for the workspace or for any repo, times one plus the buffer, reaches the reviewer's reading limit of 10,000
lines SHALL fail loading naming the repo or the workspace, the ceiling and the buffer. `abk doctor` SHALL warn when the buffered `auto`
ceiling is above 80% of that limit, and when `split_rounds` is 0 with review enabled. The planner SHALL NOT read the buffer.

#### Scenario: The defaults

- **WHEN** a workspace configures neither
- **THEN** the buffer is 0.2 and the rounds are 2

#### Scenario: A buffer out of range

- **GIVEN** `ceiling_buffer: 1.5`
- **WHEN** the configuration is loaded
- **THEN** loading fails naming the key and the value

#### Scenario: Rounds above the maximum

- **GIVEN** `split_rounds: 3`
- **WHEN** the configuration is loaded
- **THEN** loading fails naming the key and the value

#### Scenario: A buffered ceiling at the reading limit

- **GIVEN** an `auto` ceiling of 9000 and a buffer of 0.2
- **WHEN** the configuration is loaded
- **THEN** loading fails naming the ceiling, the buffer and the limit

#### Scenario: Close to the limit

- **GIVEN** an `auto` ceiling of 7000 and a buffer of 0.2
- **WHEN** `abk doctor` runs
- **THEN** it warns that the buffered ceiling of 8400 is near the reviewer's limit

### Requirement: A unit over its earned tier's buffered ceiling gets the verdict hold-and-split

The verdict SHALL, after it has found the tier a unit earns, compare the unit's changed lines (generated files left out) with the
ceiling in effect for that tier in the unit's repo times one plus `review.ceiling_buffer`, and when the lines are over it the outcome
SHALL be hold-and-split, carrying the tier earned, the tier planned, the lines, the ceiling and the reviewer's drivers as groups. A driver
that names a file SHALL be taken to name the groups of the unit whose task text names it, and one that names none SHALL be dropped. A unit
at or under the buffered ceiling SHALL keep its verdict. A unit whose verdict records `size_waived` SHALL skip this step. The step
SHALL make no model call, and a failure to compute it SHALL be logged and SHALL NOT hold the unit.

#### Scenario: Earned full, over the buffer

- **GIVEN** a unit planned `auto` that earns `full` with 950 changed lines and the default ceilings and buffer
- **WHEN** the verdict is computed
- **THEN** the outcome is hold-and-split with the drivers the reviewer named, since 950 is over 900

#### Scenario: Earned full, within the buffer

- **GIVEN** the same unit with 800 changed lines
- **WHEN** the verdict is computed
- **THEN** its tier is `full` and it is not held

#### Scenario: Over the planned ceiling with no higher tier

- **GIVEN** a unit planned and earning `light` with 2500 changed lines
- **WHEN** the verdict is computed
- **THEN** the outcome is hold-and-split with no drivers, since 2500 is over 2400

#### Scenario: A driver that is a file

- **GIVEN** a reviewer driver naming `src/billing/charge.py`, which the task text of group 3 names
- **WHEN** the verdict is computed
- **THEN** the driver is group 3

#### Scenario: A driver that matches nothing

- **GIVEN** a driver naming a file no group's task text names, and no other driver
- **WHEN** the verdict is computed
- **THEN** the outcome carries no drivers

#### Scenario: Waived by a person

- **GIVEN** a unit a person released from a size hold
- **WHEN** the verdict is computed and the unit is still over the buffered ceiling
- **THEN** the size step does not hold it, and the tier it earned stands

### Requirement: A unit held as too big for its tier is not failed and uses no review round

When the verdict computed after any review round, interim or final, is hold-and-split, the review step SHALL hold the unit at once,
without asking the builder for another round and without approving it, and SHALL NOT run the size step for a round whose reply
holds the unit for a person. It SHALL hold the unit with the cause too big for its tier, held by size, and keep the
request on the unit. It SHALL NOT mark the unit failed, SHALL NOT advance the review round and SHALL NOT use a rework round. A unit held by
size and waiting to be split SHALL raise no notification. With `review.enabled` false the step SHALL NOT run.

#### Scenario: Held, not failed

- **WHEN** a review round that approves the unit gives a verdict of hold-and-split
- **THEN** the unit is `held` with the cause and the request recorded, its review round is unchanged and it is not failed

#### Scenario: Held at the first round that shows it

- **GIVEN** a round that asks the builder for changes and whose interim verdict is hold-and-split
- **WHEN** the round is weighed
- **THEN** the unit is held by size at that round, no rework round is started, and the request is recorded

#### Scenario: Held for a person first

- **GIVEN** a round whose reply sets `needs_human` and whose verdict would be hold-and-split
- **WHEN** the round is weighed
- **THEN** the unit is held for a person for that reason and is not held by size

#### Scenario: Flag off

- **GIVEN** `review.enabled` false and a unit over any ceiling
- **WHEN** a review round ends
- **THEN** the unit goes on as before

#### Scenario: No card

- **WHEN** a unit is held by size and a split is pending
- **THEN** no card is raised for it

### Requirement: A unit that cannot be split, or has no rounds left, is held for a person with the reason

The pipeline SHALL hold a unit for a person, with the same cause and a note giving the reason, when: its lineage has used `split_rounds`
rounds or `split_rounds` is 0; it holds one group, or one group alone is estimated over the ceiling of the tier it earned; it carries groups
of another change; or a unit that has started is stacked on it. A failed or invalid re-plan SHALL count as a round, and an outage of the
network or the model service SHALL NOT. A person's `abk requeue` of such a unit SHALL record that its size is waived.

#### Scenario: Rounds spent

- **GIVEN** `split_rounds: 2` and a lineage that has used two
- **WHEN** one of its units is again over its buffered ceiling
- **THEN** it is held for a person, the note saying two of two rounds were used, and a card is raised

#### Scenario: A single oversized group

- **GIVEN** a unit of one group over the ceiling of its earned tier
- **WHEN** the pipeline looks at it
- **THEN** it is held for a person naming the group, and no planner call is made

#### Scenario: A started dependent

- **GIVEN** a held unit with a dependent that is in review on its branch
- **WHEN** a split is due
- **THEN** the unit is held for a person naming the dependent

#### Scenario: A failed re-plan uses a round

- **GIVEN** `split_rounds: 2` and a first split whose plan is refused
- **WHEN** it is tried
- **THEN** one round is recorded, the unit stays held by size and the split is tried again on the next tick

#### Scenario: An outage

- **WHEN** the network is down while a split is planned
- **THEN** no round is used and the split waits

#### Scenario: A person lets it through

- **GIVEN** a unit held for a person for its size
- **WHEN** a person runs `abk requeue` on it
- **THEN** the unit records that its size is waived and the next review's verdict does not hold it for its size

### Requirement: Per-tier sizing is on by default

`review.enabled` SHALL default to true, which is what makes the per-tier ceilings size units and the verdict's size step act, and SHALL
remain the one switch for both. A workspace that sets it false SHALL have every unit held to `max_unit_lines` (the `full` ceiling) and
no verdict computed, as before this work. Auto-land SHALL stay off until a class is listed.

#### Scenario: The default

- **WHEN** a workspace configures no `review` section
- **THEN** `review.enabled` is true, the ceilings in effect are 5000, 2000 and 750, and no class is allowed to auto-land

#### Scenario: Turned off

- **GIVEN** `review.enabled: false`
- **WHEN** a plan is checked
- **THEN** every unit is held to the `full` ceiling
