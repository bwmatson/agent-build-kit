## ADDED Requirements

### Requirement: A workspace configures a size ceiling for each review tier

The `review` section of abk.yaml SHALL accept `ceilings`, holding a ceiling in changed lines for each review tier: `auto`
(default 5000), `light` (default 2000) and `full` (default 750). The ceilings SHALL satisfy `auto` at least `light`, `light` at least
`full`, and `full` above `global_limits.min_unit_lines`, and a configuration that does not SHALL fail to load naming the tiers or the
floor and both values. An unknown tier SHALL fail loading naming it.

#### Scenario: The defaults

- **WHEN** a workspace configures no `ceilings`
- **THEN** the ceilings are 5000, 2000 and 750

#### Scenario: Out of order

- **GIVEN** `light: 900` and `full: 1200`
- **WHEN** the configuration is loaded
- **THEN** loading fails naming `light`, `full` and both values

#### Scenario: A full ceiling at the floor

- **GIVEN** `full: 400` and `min_unit_lines: 400`
- **WHEN** the configuration is loaded
- **THEN** loading fails naming `full`, the floor and both values

### Requirement: A repo may override the ceilings, and an unset tier follows the global one

A repo's `review` block SHALL accept `ceilings` with any of the three tiers. The ceiling in effect for a repo SHALL be its own value
for a tier when set and the workspace's otherwise, and the ceilings in effect for every repo SHALL satisfy the same order and floor as
the workspace's, which SHALL be checked when the configuration loads, naming the repo.

#### Scenario: One tier overridden

- **GIVEN** a global `auto: 5000` and a repo with `ceilings: {auto: 3000}`
- **WHEN** the ceilings in effect for the repo are read
- **THEN** `auto` is 3000, and `light` and `full` are the workspace's

#### Scenario: An override that breaks the order

- **GIVEN** a repo with `ceilings: {auto: 1500}` and a global `light: 2000`
- **WHEN** the configuration is loaded
- **THEN** loading fails naming the repo, `auto`, `light` and both values

### Requirement: `max_unit_lines` is deprecated and read as the full ceiling

While `global_limits.max_unit_lines` is read, it SHALL be the `full` ceiling, with a notice from `abk config` and `abk doctor` that
it is deprecated for `review.ceilings.full`. A configuration that sets it and `review.ceilings.full` to different values SHALL fail to
load naming both; set to the same value it SHALL load with the notice. `global_limits.min_unit_lines` SHALL stay and SHALL apply to
every tier.

#### Scenario: Only the old key

- **GIVEN** `global_limits.max_unit_lines: 600` and no `ceilings`
- **WHEN** the configuration is loaded
- **THEN** the `full` ceiling in effect is 600 and the notice names `review.ceilings.full`

#### Scenario: Both, disagreeing

- **GIVEN** `max_unit_lines: 600` and `review.ceilings.full: 750`
- **WHEN** the configuration is loaded
- **THEN** loading fails naming both keys and both values

#### Scenario: Both, agreeing

- **GIVEN** `max_unit_lines: 750` and `review.ceilings.full: 750`
- **WHEN** the configuration is loaded
- **THEN** it loads, with the notice

### Requirement: Per-tier ceilings take effect only when `review.enabled` is true

With `review.enabled` false every unit SHALL be held to the `full` ceiling in effect, which is `max_unit_lines` for a workspace that sets
only it, and the planner's instructions, the plan check and the size comparison SHALL be as they were before the ceilings existed. With
it true each unit SHALL be held to the ceiling of its expected review tier.

#### Scenario: Flag off

- **GIVEN** `review.enabled` false and a unit expected to get `auto` review estimated at 2000 lines
- **WHEN** the plan is checked
- **THEN** the plan is refused as over the ceiling of 750

#### Scenario: Flag on

- **GIVEN** `review.enabled` true and the same unit
- **WHEN** the plan is checked
- **THEN** the unit is accepted

### Requirement: The planner is told each tier's ceiling and holds each unit to its own

With per-tier sizing on, the planner's instructions SHALL state the ceiling for each review tier and each overriding repo's, and say
that a unit is held to the ceiling of the tier it is expected to get. The plan check SHALL refuse a unit whose estimate, multiplied by
its kind's calibration ratio, exceeds the ceiling of its expected tier, naming the tier, the ceiling, the ratio and the samples behind
it, and a unit with no expected tier SHALL be held to the `full` ceiling. A single group over its unit's ceiling SHALL be reported as
needing its tasks split, naming the tier. The planner SHALL plan to the plain ceilings.

#### Scenario: The prompt

- **GIVEN** per-tier sizing on and a repo overriding `auto`
- **WHEN** the planner is instructed
- **THEN** its instructions give the three ceilings and the repo's override

#### Scenario: A light unit over its ceiling

- **GIVEN** a unit expected to get `light` review estimated at 2100 lines with a ratio of 1.0
- **WHEN** the plan is checked
- **THEN** it is refused, naming `light`, 2000 and 2100

#### Scenario: A calibrated figure

- **GIVEN** a ratio of 1.5 and a unit expected to get `auto` estimated at 3500
- **WHEN** the plan is checked
- **THEN** it is refused, the message naming 5250, 5000, the ratio and its samples

#### Scenario: One oversized group

- **GIVEN** a single group estimated at 5400 in a unit expected to get `auto`
- **WHEN** the plan is checked
- **THEN** the change is left unplanned with a message naming the group, the tier and saying its tasks must be split

#### Scenario: No expected tier

- **GIVEN** a unit with no expected review tier estimated at 800
- **WHEN** the plan is checked
- **THEN** it is refused as over the `full` ceiling of 750

### Requirement: A group that expects full review does not share a unit with other work

The planner's instructions SHALL tell it to keep a group it expects to get full review in a unit with only such groups, and the plan
check SHALL refuse a plan in which a unit holds a group whose floor is `full` (flagged `contract`, `narrow` or `acceptance`, or naming a
protected path in its task text) and a group whose floor is lower, naming the unit and the groups. A join SHALL be refused when it would
do the same.

#### Scenario: A protected-path group beside an ordinary one

- **GIVEN** a group whose task text names `db/migrations/0042_add_index.sql` and an unflagged group with no protected path
- **WHEN** a plan puts them in one unit
- **THEN** the plan is refused naming the unit and both groups

#### Scenario: Two full groups

- **WHEN** a plan puts two groups whose floors are `full` in one unit
- **THEN** the separation rule does not refuse it

#### Scenario: A join

- **GIVEN** an unstarted unit of ordinary groups and a group flagged `contract`
- **WHEN** the planner proposes joining the group onto the unit
- **THEN** the join is refused

### Requirement: A joined unit takes the highest tier and that tier's ceiling

A unit that takes in a group or another unit SHALL be expected to get the higher of the two tiers, a joined group counting at its floor,
and the join SHALL be refused when the combined estimate, multiplied by the receiving unit's kind's ratio, exceeds the ceiling of that
tier, naming the tier.

#### Scenario: A light unit joined with an auto unit

- **GIVEN** two unstarted units expected to get `auto` and `light` review, in a line, with a combined estimate of 2500
- **WHEN** the planner proposes the join
- **THEN** the join is refused naming `light` and 2000

#### Scenario: Two auto units

- **GIVEN** two such units both expected to get `auto`, combined 2500
- **WHEN** the join is proposed
- **THEN** it is accepted

### Requirement: A unit's actual size is compared with its tier's ceiling

Where a unit's actual size is compared with the ceiling (the log line when its pull request lands over it, and the status listing),
per-tier sizing SHALL compare it with the ceiling of the unit's expected tier, without a buffer.

#### Scenario: A light unit landing over 2000

- **GIVEN** per-tier sizing on and a unit expected to get `light` review whose pull request changes 2300 lines
- **WHEN** the pull request is opened
- **THEN** its log and the status say it is over the ceiling of 2000

#### Scenario: An auto unit under its own ceiling

- **GIVEN** a unit expected to get `auto` review whose pull request changes 2300 lines
- **WHEN** it is opened
- **THEN** nothing is said of its size

### Requirement: `abk config --migrate` moves `max_unit_lines` to `review.ceilings.full`

`abk config --migrate` SHALL move a `max_unit_lines` under `global_limits` or under the deprecated root `limits` to
`review.ceilings.full`, creating the `review` and `ceilings` blocks when absent, by editing the file's text and changing no other byte,
with its end-of-line comment and the comment lines directly above it, and SHALL check that the result loads with the same ceilings in
effect before it writes. It SHALL refuse, naming the file and the key and writing nothing, when `review.ceilings.full` is already set
to a different value, when the key's value spans lines or carries an anchor, or when the file has several documents. Run again over its
own result it SHALL change nothing. It SHALL do this in the same single change, confirmation and write as the other moves it makes.

#### Scenario: The move

- **GIVEN** a file with `global_limits.max_unit_lines: 900` and a comment at the end of that line
- **WHEN** `abk config --migrate` runs and the change is confirmed
- **THEN** `review.ceilings.full` is 900 with the comment, the old key is gone, and every other line is as it was

#### Scenario: Both set to different values

- **GIVEN** `max_unit_lines: 900` and `review.ceilings.full: 800`
- **WHEN** the command runs
- **THEN** it refuses naming both keys and writes nothing

#### Scenario: Idempotent

- **WHEN** the command runs over a file it has already migrated
- **THEN** it reports nothing to move and writes nothing
