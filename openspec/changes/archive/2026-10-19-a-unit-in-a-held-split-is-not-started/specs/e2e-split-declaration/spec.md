## ADDED Requirements

### Requirement: An e2e-test group declares its tier 2 split with a `Split:` line

A task group MAY carry a line `Split: <name>` on its own, inside the group, after its heading (where `Needs:` and `Priority:` lines go). The key
SHALL be read case-insensitively. The name SHALL be a split declared for the group's repo (`tests.e2e_splits`, the repo's own map replacing the
top-level one) or `rest`. A group with no line SHALL be in `rest`, and `Split: rest` SHALL mean the same. Only a group tagged `[e2e-test]` SHALL
carry the line; a `[unit-test]` group has no tier 2 and a `Split:` line in one SHALL be refused with that reason. A name that is not declared for
the repo SHALL be refused naming the repo and the splits it declares; a repo that declares no splits SHALL accept `rest` and no other name, and
SHALL behave as it does today when no group names one. A `Split:` line above the first group SHALL be refused, and so SHALL one in a group
whose heading could not be read. Plan validation and `abk tags` SHALL report each refusal with its line and a clear message, and SHALL NOT start
a plan on a refused group. The parsed split SHALL be part of the group, with `rest` when the line is absent.

#### Scenario: A declared split

- **GIVEN** a repo declaring the splits `claude_code` and `acp`
- **WHEN** an e2e-test group carries `Split: acp`
- **THEN** its split is `acp` and `abk tags` reports no problem

#### Scenario: No line is rest

- **GIVEN** an e2e-test group with no `Split:` line
- **WHEN** the tasks are parsed
- **THEN** its split is `rest`, and so it is with `Split: rest`

#### Scenario: A name the repo does not declare

- **GIVEN** a repo declaring `claude_code` and `acp`
- **WHEN** a group carries `Split: gpu`
- **THEN** `abk tags` refuses it at the line naming the repo and the declared splits `claude_code`, `acp` and `rest`

#### Scenario: A repo with no splits

- **GIVEN** a repo that declares no splits
- **WHEN** a group carries `Split: acp`
- **THEN** it is refused saying the repo declares none; a group with no line, or with `Split: rest`, is accepted and behaves as before

#### Scenario: A unit-test group

- **WHEN** a `[unit-test]` group carries a `Split:` line
- **THEN** it is refused because a unit-test group has no tier 2

#### Scenario: A line outside a group

- **WHEN** a `Split:` line is above the first group heading
- **THEN** it is refused as belonging to no group

#### Scenario: The key's case

- **WHEN** a group carries `split: acp`
- **THEN** it is read as `Split: acp`

### Requirement: A group is in one split, and a test in two splits is two groups

A group SHALL name at most one split. A second `Split:` line in the same group, and a value naming more than one (a comma or a space between
names), SHALL be refused with a message that says a group is in one split and that a test which must run in two splits is written as two groups,
one for each. The pipeline SHALL NOT divide a group by itself. Groups of different splits SHALL NOT be joined into one unit: a unit SHALL carry
one split, the one all its groups share, and SHALL record it when it is planned. A plan that puts groups of two splits in one unit, and a join of a
group or an unstarted unit onto a unit of another split, SHALL be refused as a join of another repo or kind is, naming the split. Groups of
`rest` and of a declared split in the same change SHALL be separate units.

#### Scenario: Two lines

- **WHEN** a group carries `Split: acp` and a later line `Split: claude_code`
- **THEN** the second is refused as a second split for the group, with the instruction to write two groups

#### Scenario: Two names on a line

- **WHEN** a group carries `Split: claude_code, acp`
- **THEN** it is refused with the same instruction, and nothing is split for the author

#### Scenario: A test for two splits

- **GIVEN** an e2e test written as group 2 in split `claude_code` and group 3 in split `acp`
- **WHEN** the change is planned
- **THEN** groups 2 and 3 are two units, group 2 able to merge while `acp` is held

#### Scenario: A plan that mixes splits

- **WHEN** a plan puts groups of splits `claude_code` and `acp` in one unit
- **THEN** the plan is refused naming the groups and their splits

#### Scenario: A unit's split

- **WHEN** a unit is planned from groups in split `acp`
- **THEN** its record carries the split `acp`, and a unit planned from groups with no line carries `rest`

#### Scenario: A record from before

- **WHEN** a stored unit has no split
- **THEN** it reads as `rest`
