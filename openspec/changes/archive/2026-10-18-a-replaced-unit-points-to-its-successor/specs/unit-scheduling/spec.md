## ADDED Requirements

### Requirement: A unit a replan replaced records the units that carry its groups now

When a unit becomes `unplanned` by a replan, or is found `unplanned` or `retired` with no record of it, the store SHALL record in the unit's `superseded_by`
the ids of the units that carry its groups: every unit other than it, not `unplanned`, `retired` or `closed`, that builds any `(change, group)` pair the
replaced unit built, its own groups and joined ones, in id order. A merged or satisfied unit SHALL be recorded like a live one. The record SHALL be made
in the same write that sets the state. When no unit carries any of its groups the field SHALL stay empty. A field that is not empty SHALL NOT be
overwritten. The field SHALL be left out of the stored record when empty, so a store with no replaced unit reads and writes as before and a store written
before the field reads with it empty. A unit the plan asks for again SHALL lose it. A join SHALL delete the unit it takes in and, in the same write,
repoint `depends_on`, `needs`, `waited_on` and `superseded_by` of every unit from it to the unit that took it in.

#### Scenario: A join of two groups renumbers the unit

- **GIVEN** a change whose unstarted units `x/3` (group 3) and `x/4` (group 4) are replaced by a replan with one new unit `x/5` that carries groups 3 and 4
- **WHEN** the replan is stored
- **THEN** `x/3` and `x/4` are `unplanned`, each with `superseded_by` `x/5`, and the demotion's history entry says `replaced by x/5`

#### Scenario: A split

- **GIVEN** an unstarted unit carrying groups 3 and 4 that a replan replaces with a unit for group 3 and a unit for group 4
- **WHEN** the replan is stored
- **THEN** its `superseded_by` lists both new units

#### Scenario: Nothing carries the groups

- **GIVEN** a replan that no longer contains a group
- **WHEN** the unit that carried it is set `unplanned`
- **THEN** its `superseded_by` is empty and is left out of the stored record

#### Scenario: A merged unit carries them

- **GIVEN** a replaced unit whose groups a merged unit of the same change carries
- **WHEN** the replan is stored
- **THEN** the merged unit is its successor

#### Scenario: A retired unit

- **GIVEN** a unit ended by `abk retire` whose groups a later plan gives to a new unit
- **WHEN** the plan is stored or a tick runs
- **THEN** the retired unit's `superseded_by` is that unit, and a retired unit whose groups nothing carries has none

#### Scenario: The plan asks for the unit again

- **GIVEN** an `unplanned` unit with a successor
- **WHEN** a replan contains the unit
- **THEN** it is planned and its `superseded_by` is empty

#### Scenario: A set field is kept

- **GIVEN** a replaced unit whose successor was itself replaced later
- **WHEN** the store records successors again
- **THEN** the first unit's `superseded_by` is unchanged

#### Scenario: A store from an earlier release

- **GIVEN** a units file with no `superseded_by` anywhere
- **WHEN** it is loaded and written
- **THEN** every unit reads with it empty and the written file has no such key

#### Scenario: A join

- **GIVEN** an unstarted unit taken into another by a join, a started unit that depends on it and a unit whose `superseded_by` names it
- **WHEN** the join is written
- **THEN** the taken unit is gone and the other two name the unit that took it in, once each

### Requirement: A dependency on a replaced unit is read as the units that carry its work

Every reader of a unit's dependencies SHALL read one resolved list, the stored dependencies with each entry that names an `unplanned` or `retired` unit
that has successors replaced by its successors, followed through further replaced units to at most eight links, once each, in order, never the unit
itself. A replaced unit that has no successors, a successor that is missing, and a cycle in the field SHALL stand for the unit named, so the readers that
skip a unit that builds nothing skip it. A merged, satisfied or closed result SHALL be passed on unchanged, to be treated as any finished parent. The scheduler, the stack's base and depth, the build's check at a step boundary, the follow pass, the restack, the wait for room, promotion, the cycle checks, the retire command, the planner's view, the diagram and the graph page SHALL all read it, so none disagrees about what a unit depends on.

#### Scenario: The wait follows the successor

- **GIVEN** a started unit whose stored dependency is a replaced unit and whose successor is `planned`
- **WHEN** the scheduler and the build's check at a step boundary read its dependencies
- **THEN** both name the successor and neither names the replaced unit

#### Scenario: A chain

- **GIVEN** `a` replaced by `b`, `b` replaced by `c`, and a unit that depends on `a`
- **WHEN** its dependencies are read
- **THEN** they are `c`

#### Scenario: A chain longer than the bound

- **GIVEN** ten replaced units in a line and a dependent of the first
- **WHEN** its dependencies are read
- **THEN** the read ends at the eighth link

#### Scenario: A merged successor

- **GIVEN** a dependency on a replaced unit whose successor is merged
- **WHEN** the scheduler reads it
- **THEN** the dependent does not wait for it, as for any merged parent, and the status shows it as covered

#### Scenario: No successor

- **GIVEN** a dependency on a replaced unit with an empty `superseded_by`
- **WHEN** it is read
- **THEN** it names that unit, and the rule for a parent that builds nothing applies to it

#### Scenario: The cycle checks

- **GIVEN** a plan edge that would close a cycle only through the successor of a replaced unit a stored unit depends on
- **WHEN** the plan is checked
- **THEN** the edge is dropped and the cycle is named

### Requirement: A tick repoints a stored dependency on a replaced unit

Each tick after planning, and in `abk replan`, a dependency stored on any unit that has not finished, started or not, that names a replaced unit with
successors SHALL be replaced in place by its live successors. When the unit's `Needs:` lines resolve to some of those successors only those SHALL be
taken; when it has none, every successor SHALL be. A successor that would close a cycle SHALL be refused and logged as a refused `Needs:` is; the rest SHALL be taken, and with none left the stored dependency SHALL stay. The write SHALL be logged `<unit>: dependency <old> is now <new> (replaced by a
replan)`. An edge with no successor SHALL NOT be changed by this requirement; the rule for a stored dependency on a unit that builds nothing applies to
it, and it SHALL come after this one, so an edge that has a successor is repointed and never dropped. A second tick SHALL change nothing.

#### Scenario: A started dependent after a join

- **GIVEN** a running unit that depends on `x/3`, replaced by `x/5`
- **WHEN** the tick links
- **THEN** it depends on `x/5`, `x/3` is gone from its dependencies, and the log says `dependency x/3 is now x/5 (replaced by a replan)`

#### Scenario: A split and a planner edge

- **GIVEN** a unit with a planner dependency on a unit replaced by two units, and no `Needs:` line
- **WHEN** the tick links
- **THEN** it depends on both

#### Scenario: A split and a `Needs:` line

- **GIVEN** a unit whose `Needs: x group 3` line resolves to one of two successors of a replaced unit it still stores
- **WHEN** the tick links
- **THEN** it depends on that successor only

#### Scenario: A merged successor

- **GIVEN** a stored dependency on a replaced unit whose successor is merged
- **WHEN** the tick links
- **THEN** the dependency is the merged unit, and the unit's wait is the same as before

#### Scenario: No successor

- **GIVEN** a stored dependency on a replaced unit with an empty `superseded_by`
- **WHEN** the tick links
- **THEN** this requirement changes nothing, and the dependency is left to the rule for a parent that builds nothing

#### Scenario: A successor that would close a cycle

- **GIVEN** a successor that already waits on the dependent
- **WHEN** the tick links
- **THEN** the log names the cycle, the dependent keeps its stored dependency, and the refusal is not logged again for the same pair

#### Scenario: Run again

- **WHEN** the tick links a second time
- **THEN** nothing is changed and nothing is logged

### Requirement: A wait recorded on a replaced unit follows its successor

A failed unit's recorded wait (`waited_on`) SHALL be judged on the units that stand in for each recorded id. A recorded id that is a replaced unit with
successors SHALL NOT end the wait as a prerequisite that was closed: while a successor is unreviewed the record SHALL name it; when every successor is
reviewed or merged the unit SHALL be requeued as for any wait that ended. A replaced unit with no successors SHALL end the wait as a closed prerequisite
does. The planner SHALL be shown a replaced unit as replaced by its successors, and an unstarted unit's dependencies as the resolved list. History notes, feedback and guidance SHALL stay as written.

#### Scenario: The successor lands

- **GIVEN** a failed unit that was recorded waiting on `x/3`, now replaced by `x/5`, which is in review
- **WHEN** the tick requeues units whose wait ended
- **THEN** the unit is requeued once and no `wait_ended` is recorded

#### Scenario: The successor is still building

- **GIVEN** the same unit with `x/5` planned
- **WHEN** the tick runs
- **THEN** the record names `x/5`, and the unit keeps waiting

#### Scenario: Nothing carries the work

- **GIVEN** a recorded wait on a replaced unit with no successors
- **WHEN** the tick runs
- **THEN** the unit stays failed with `wait_ended` naming it

#### Scenario: The planner's view

- **GIVEN** an `unplanned` unit with a successor and an unstarted unit with a stored dependency on it
- **WHEN** the planner is shown the in-flight units
- **THEN** the first reads `replaced by` the successor, still saying what it built, and the second depends on the successor

### Requirement: The status, the replan report and the graph show a replaced unit with its successor

`abk replan` SHALL report a unit it set `unplanned` as `now unplanned, replaced by <ids>` when it has successors. `abk status` SHALL list, as `replaced:
<unit> by <ids>`, each replaced unit that an unfinished unit's stored dependencies, `needs` or recorded wait still name, which is a pass that has not yet
run. The graph page's unit data SHALL give a replaced unit its successors, and its dependencies SHALL be the resolved list. The diagram SHALL draw an edge
to a replaced unit from its successor.

#### Scenario: The replan report

- **GIVEN** a replan that joins two unstarted units into one
- **WHEN** it prints what changed
- **THEN** each replaced unit is reported as `now unplanned, replaced by` the new unit

#### Scenario: A reference not yet repointed

- **GIVEN** a replaced unit with a successor that a started unit still names
- **WHEN** `abk status` is read before the next tick
- **THEN** one `replaced:` line names the unit and its successor

#### Scenario: The graph data

- **GIVEN** a unit that depends on a replaced unit
- **WHEN** the unit's data is read
- **THEN** its dependencies are the successors, and the replaced unit's data lists them as `replaced_by`

### Requirement: Units replaced before successors were recorded are given them once

Each tick, before linking, the store SHALL give every `unplanned` or `retired` unit with an empty `superseded_by` the successors the current store
computes, in one write, and the tick SHALL log `successors recorded: <n> unit(s)` when it wrote any. A unit nothing carries SHALL stay empty and be computed again later, and a unit that has successors SHALL NOT be written again. A second run SHALL write nothing.

#### Scenario: Two stale dependents

- **GIVEN** an `unplanned` unit with no record whose groups a live unit carries, and two units that depend on it
- **WHEN** the first tick after the release runs
- **THEN** the unit has the live unit as successor, the two are repointed to it in the same tick, and the log says `successors recorded: 1 unit(s)`

#### Scenario: A renumbered legacy unit is given its successor once

- **GIVEN** an `unplanned` unit with no record that an earlier release renumbered, so that a live unit now carries exactly its groups, and a started unit that depends on it
- **WHEN** the first tick after the release runs, and then a second
- **THEN** the first records that unit as the successor and repoints the dependent, and the second writes nothing and logs nothing

#### Scenario: Idempotent

- **WHEN** the tick runs again
- **THEN** the store is not written and nothing is logged

#### Scenario: Nothing carries them

- **GIVEN** an `unplanned` unit whose groups no unit carries
- **WHEN** the tick runs
- **THEN** its field is empty and it is not counted

### Requirement: A replan keeps a rebuilt unit's runtime fields except the one that says it was replaced

A unit that a replan contains SHALL be live, so the record of what replaced it SHALL be empty after the replan, whatever it held; every other field the
replan keeps SHALL be kept as before. A unit that a replan does not contain SHALL keep it.

#### Scenario: Revived

- **GIVEN** an `unplanned` unit with `superseded_by` and a replan that contains it
- **WHEN** the replan is stored
- **THEN** the unit is planned, its record has no `superseded_by`, and its other runtime fields are as they were

## MODIFIED Requirements

### Requirement: A replan clears a stale planner edge and leaves started units alone

A replan SHALL replace the dependencies of a unit that has not started with the plan's, so a planner dependency dropped for a cycle is gone from the
stored unit. The dependencies of a unit that has started SHALL never be changed by a plan, a dropped edge or a refused `Needs:`. The linking that follows
a plan MAY replace a stored dependency on a replaced unit by its successors, in a unit of any state, as the requirement on repointing says; it SHALL
change no other dependency of a started unit.

#### Scenario: A stale edge on an unstarted unit

- **WHEN** an unstarted unit stores a planner dependency that closes a cycle and its change is replanned
- **THEN** the stored unit no longer has it and its state, branch and history are unchanged

#### Scenario: A started unit

- **WHEN** a running, in-review, failed or held unit of the change has dependencies and the change is replanned
- **THEN** its dependencies are the same afterwards, and a cycle through it is reported rather than edited
