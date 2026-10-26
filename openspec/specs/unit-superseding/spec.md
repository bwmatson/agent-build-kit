# unit-superseding Specification

## Purpose
TBD - created by archiving change a-unit-over-its-tier-is-held-and-split. Update Purpose after archive.

## Requirements

### Requirement: A held unit is superseded by the units that replace it

When a unit held by size is split, the pipeline SHALL record it as closed with the cause superseded and the ids of the units that
replace it, in one write that also adds those units as planned and re-points to the last of them every other unit's dependency and `Needs:`
target that named it. Its groups SHALL then not count as taken, it SHALL occupy no slot, and it SHALL NOT make its change wait for a merge:
the change is ready to archive when the units that carry its groups have merged. The unit SHALL keep its branch and pull request number.

#### Scenario: A split of a unit in the middle of a change

- **GIVEN** `app/3`, held by size, with a later unit `app/4` that depends on it
- **WHEN** it is split into `app/3-s1` and `app/3-s2`
- **THEN** `app/3` is closed with the cause superseded and both ids, `app/4` depends on `app/3-s2`, and `app/3-s2` depends on `app/3-s1`

#### Scenario: Its groups are free

- **WHEN** a unit is superseded
- **THEN** the groups it carried are not taken, are not required to still be in `tasks.md`, and the units that carry them are planned in its place

#### Scenario: Archiving

- **GIVEN** a change whose units are merged except a superseded one whose pieces merged
- **WHEN** archiving asks whether the change is ready
- **THEN** it is ready

#### Scenario: A slot

- **WHEN** a unit is superseded
- **THEN** it does not count among the units in progress

### Requirement: A superseded unit's pull request is closed with a comment naming the new units

The pipeline SHALL close the pull request of a superseded unit after posting a comment that names the units that replace it, the lines,
the ceiling and the tier, and a close that fails SHALL be kept and retried on later passes. The host's closed event for that pull request
SHALL leave the unit as it is, and SHALL NOT replace its cause.

#### Scenario: Comment, then close

- **GIVEN** a superseded unit with pull request 17
- **WHEN** the close is made
- **THEN** a comment naming the new units is posted on 17 before it is closed

#### Scenario: The closed event

- **WHEN** the poller reports that pull request 17 closed
- **THEN** the unit is still closed with the cause superseded

#### Scenario: A close that fails

- **WHEN** the host refuses the close
- **THEN** the close stays pending and is tried again on the next pass

### Requirement: The old branch is kept under a ref

Before a unit is superseded the pipeline SHALL keep its branch's tip under a ref in the repo, `refs/spec-driven/superseded/<unit id>`,
with the unit's branch lock held, and SHALL NOT delete the remote branch. A unit whose branch a live process holds SHALL NOT be superseded
until it is free.

#### Scenario: Kept

- **WHEN** a unit is superseded
- **THEN** the ref points at the branch's tip at that moment

#### Scenario: A branch in use

- **GIVEN** a process holds the unit's branch lock
- **WHEN** the split is due
- **THEN** nothing is changed and the split is tried again later

### Requirement: A piece's id extends its parent's and can never collide

A unit made by a split SHALL have the id of the unit it replaces followed by `-s<k>`, where `k` counts from 1 in the order of the pieces,
and its branch SHALL be named from that id as any unit's is. A plan SHALL NOT use the id of a superseded unit. The number a unit's id is
sorted by SHALL be the integer that follows the change's name, so a piece sorts where its root did, and a unit's run logs and transcripts
SHALL be told apart from its parent's.

#### Scenario: Ids

- **WHEN** `app/3` is split into two and `app/3-s2` is later split into two
- **THEN** the ids are `app/3-s1`, `app/3-s2`, `app/3-s2-s1` and `app/3-s2-s2`

#### Scenario: A retired id

- **GIVEN** `app/3` is superseded
- **WHEN** a plan of the change proposes a unit with the id `app/3`
- **THEN** the plan is refused naming the id

#### Scenario: Ordering

- **GIVEN** a narrowing unit `app/5` and a piece `app/3-s1`
- **WHEN** the units that come before the narrowing unit are listed
- **THEN** the piece is among them

#### Scenario: Logs

- **WHEN** `app/3` and `app/3-s1` have both run
- **THEN** each unit's run logs and transcripts are found by its own id and not by the other's
