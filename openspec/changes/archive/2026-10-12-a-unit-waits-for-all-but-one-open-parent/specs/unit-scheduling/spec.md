## ADDED Requirements

### Requirement: A unit waits for all but one of its unrelated open parents

A unit's open parents SHALL be its dependencies in its own repository that are in review, looking through a satisfied dependency to what it
was built on. Two open parents SHALL be related when one is reachable from the other through dependencies, and a unit's unrelated open parents
SHALL be those that no other open parent builds on. A unit that has never started and has two or more unrelated open parents SHALL NOT be
ready: it SHALL wait for all of them but one, and SHALL be ready once at most one remains, the others having merged, been closed or been
satisfied with their work landed. The one it does not wait for SHALL be its base: the unrelated open parent with the greatest stack depth, a
tie going to the one later in plan order. When the open parents form a chain, the unit SHALL be built on the newest, the one that builds on
the others, whatever order its dependencies are listed in. No branch SHALL be made by combining the branches of several parents. A
dependency in another repository SHALL keep waiting for a merge as before and SHALL NOT count as an open parent.

#### Scenario: Two sibling parents in review

- **GIVEN** a unit that has not started and depends on two units of its repository that are both in review, neither built on the other
- **WHEN** the scheduler works out what is ready
- **THEN** the unit is not ready, and it waits for the one of the two that is not its base: the shallower, or for equal depth the earlier in plan order

#### Scenario: One of the siblings merges

- **GIVEN** a unit waiting for one of two sibling parents
- **WHEN** that parent merges, is closed, or is satisfied with its work landed
- **THEN** the unit is ready, and its base is the branch of the other parent

#### Scenario: Three sibling parents

- **GIVEN** a unit that has not started and depends on three unrelated open parents
- **WHEN** the scheduler works out what is ready
- **THEN** it waits for two of them, and the one that is not named is its base

#### Scenario: A chain of parents

- **GIVEN** parent B built on parent A, both in review, and a unit that depends on A and on B
- **WHEN** the scheduler works out what is ready
- **THEN** the unit is ready and its base is B, whichever order its dependencies list A and B in

#### Scenario: A diamond

- **GIVEN** two sibling units in review that were both built on one root, and a unit that depends on both siblings
- **WHEN** the scheduler works out what is ready
- **THEN** it behaves as for two sibling parents, and the root is never named as something it waits for

#### Scenario: A satisfied parent is looked through

- **GIVEN** a unit that depends on a satisfied unit and on another unit in review, and the satisfied unit was built on an in-review unit that is not built on the other
- **WHEN** the scheduler works out what is ready
- **THEN** the unit waits as for two sibling parents, because the satisfied unit is replaced by what it was built on

#### Scenario: A cross-repo parent

- **GIVEN** a unit that depends on one in-review unit of its repository and on a unit of another repository that has not merged
- **WHEN** the scheduler works out what is ready
- **THEN** it waits for the merge of the cross-repository unit as before, and does not wait for a second open parent

#### Scenario: A parent sent back for rework

- **GIVEN** a unit waiting for one of two sibling parents
- **WHEN** the other parent is sent back for rework
- **THEN** the unit waits for it as for any dependency, and is ready again only when it is back in review and the other conditions hold

### Requirement: A unit that has started is not made to wait for a second parent

The wait for a second open parent SHALL apply only to a unit that has not started. A unit that has started SHALL keep the branch it started on,
SHALL NOT be blocked by this rule, SHALL be counted as it is today, and SHALL NOT be requeued or moved off its branch when a parent is
added or appears later.

#### Scenario: A started unit with two open parents

- **GIVEN** a unit with a recorded branch and a pull request whose dependencies are two in-review units, neither built on the other
- **WHEN** the scheduler and the count of units in progress are worked out
- **THEN** the unit waits for nothing it did not wait for before and is counted as before

#### Scenario: A parent added after the unit started

- **GIVEN** a started unit and a replan that gives it a second in-review parent
- **WHEN** the next tick runs
- **THEN** nothing about the unit changes: its branch, base, state and wait are the same

### Requirement: The wait for a second open parent is shown

The status, the ready-queue reason and the graph SHALL show a unit that waits for a second open parent as waiting, naming the parent that must
merge and saying it is the second open parent, and the unit SHALL be blocked as any planned unit that waits on another unit is. The wait SHALL come from
the same answer the scheduler uses, so no consumer reports the unit as ready while the scheduler holds it back.

#### Scenario: The status

- **GIVEN** a unit waiting for one of two sibling parents
- **WHEN** the status is read
- **THEN** it says the unit waits for that parent to merge, as the second open parent

#### Scenario: The graph and the count

- **GIVEN** the same unit
- **WHEN** the graph is drawn and the units in progress are counted
- **THEN** the unit is drawn as blocked, and is counted as any blocked unit is

### Requirement: A change whose groups will give a unit unrelated parents is warned about

`abk tags` and `abk check` SHALL warn, without failing, when a change's task groups can produce a unit with unrelated open parents: an `[acceptance]`
or `[narrow]` group that follows an independent group of its repository, an independent group followed by a later group of its repository, or a
`Needs:` line to a group of another change in the repository of the group's predecessor. The warning SHALL name the group and the shape, in the
form of the other tag warnings, and SHALL NOT change the exit code, the plan or the planner's instructions.

#### Scenario: Acceptance after an independent group

- **GIVEN** a change with an `Independent:` group and an `[acceptance]` group after it, in the same repository
- **WHEN** `abk tags` is run for the change
- **THEN** it prints a warning naming the acceptance group and the shape, and exits as it would without it

#### Scenario: A needs line beside a predecessor

- **GIVEN** a group whose predecessor is in the same repository and which has a `Needs:` line to a same-repository group of another change
- **WHEN** `abk check` is run
- **THEN** it prints a warning naming the group and the shape

#### Scenario: A plain chain is silent

- **GIVEN** a change whose groups form one chain, or whose parallel groups are in different repositories
- **WHEN** `abk tags` is run
- **THEN** no warning is printed

#### Scenario: The planner is told nothing new

- **GIVEN** a change that gets the warning
- **WHEN** it is planned
- **THEN** the planner's prompt and the plan are the same as without this requirement
